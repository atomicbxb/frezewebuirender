# Monkey patching will be handled by Gunicorn. Remove explicit call from here.
# from gevent import monkey
# monkey.patch_all(thread=False, signal=False)

import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup
import traceback 
import os
from datetime import datetime
import time # For rate limiting delay

# --- API Configuration (loaded by app.py using os.getenv) ---
# These will be populated by os.getenv when the module is first imported by app.py
# Ensure app.py calls load_dotenv() BEFORE importing this module.
API_USERNAME = os.getenv("API_USERNAME")
API_KEY = os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL")
API_LOGIN_ACTION_PATH = os.getenv("API_LOGIN_ACTION_PATH")
API_EXECUTE_PATH = os.getenv("API_EXECUTE_PATH")

# --- Rate Limiting for API Calls ---
# Target: 5 requests per second.
# This means 1 request every (1 / 5) = 0.2 seconds.
# We'll use an asyncio.Semaphore to limit concurrency and a small delay.
# Semaphore limits how many can *try* to acquire it at once.
# The delay enforces the per-second rate.
API_REQUEST_SEMAPHORE = asyncio.Semaphore(5) # Allow up to 5 concurrent *attempts* to acquire
MIN_INTERVAL_BETWEEN_REQUESTS = 1.0 / 5.0  # 0.2 seconds
last_api_request_time = 0 # time.monotonic()

async def send_freeze_droid_web_rate_limited(target_number, log_callback=None):
    """
    Wrapper for send_freeze_droid_web that includes rate limiting.
    """
    global last_api_request_time
    async with API_REQUEST_SEMAPHORE:
        # Ensure minimum interval since last request
        current_time = time.monotonic()
        time_since_last = current_time - last_api_request_time
        if time_since_last < MIN_INTERVAL_BETWEEN_REQUESTS:
            sleep_duration = MIN_INTERVAL_BETWEEN_REQUESTS - time_since_last
            if log_callback: # log_callback is async
                 await log_callback(f"[{datetime.now().strftime('%H:%M:%S')}] Rate limiting: sleeping for {sleep_duration:.2f}s before API call to {target_number}")
            await asyncio.sleep(sleep_duration)
        
        last_api_request_time = time.monotonic() # Update last request time
        return await send_freeze_droid_web_actual(target_number, log_callback)


async def send_freeze_droid_web_actual(target_number, log_callback=None): # Renamed original function
    """
    Actual API call logic. log_callback is an async function.
    """
    async def _log(message):
        if log_callback:
            try:
                await log_callback(f"[{datetime.now().strftime('%H:%M:%S')}] Target {target_number} (API): {message}")
            except Exception as e_log:
                print(f"CRITICAL: Error in log_callback for target {target_number}: {e_log}")

    # This check is now primarily in app.py before calling, but good to have defense in depth
    if not all([API_USERNAME, API_KEY, API_BASE_URL, API_LOGIN_ACTION_PATH, API_EXECUTE_PATH]):
        await _log("❌ API configuration incomplete on server. Critical error.")
        return False, "Server-side API configuration error. Please contact admin."

    try:
        timeout = aiohttp.ClientTimeout(total=60) 
        base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,id;q=0.8',
        }
        login_url = f"{API_BASE_URL}/{API_LOGIN_ACTION_PATH}"
        execute_url = f"{API_BASE_URL}/{API_EXECUTE_PATH}"
        login_payload = {'username': API_USERNAME, 'key': API_KEY}

        async with aiohttp.ClientSession(timeout=timeout) as session:
            await _log("🔄 Attempting API Login...")
            login_post_headers = base_headers.copy()
            login_post_headers['Referer'] = API_BASE_URL + "/" 
            login_post_headers['Origin'] = API_BASE_URL
            
            async with session.post(login_url, data=login_payload, headers=login_post_headers, allow_redirects=True) as login_response:
                login_response_text = await login_response.text()
                current_url_after_login_post = str(login_response.url)
                await _log(f"ℹ️ Login POST status: {login_response.status}")

                expected_url_after_login = f"{API_BASE_URL}/{API_EXECUTE_PATH}"

                if not (200 <= login_response.status < 300) or \
                   API_LOGIN_ACTION_PATH in current_url_after_login_post or \
                   "<title>HASCLAW API Login</title>" in login_response_text or \
                   "Login akun anda" in login_response_text or \
                   not current_url_after_login_post.startswith(expected_url_after_login):
                    await _log("❌ API Login POST failed or did not redirect as expected.")
                    return True, login_response_text 

                await _log("✅ API Login POST successful.")

            execute_params = {'target': target_number}
            await _log(f"🔄 Executing action...") 
            execute_get_headers = base_headers.copy()
            execute_get_headers['Referer'] = current_url_after_login_post 

            async with session.get(execute_url, params=execute_params, headers=execute_get_headers) as execute_response:
                execute_response_text = await execute_response.text()
                await _log(f"ℹ️ Execute GET status: {execute_response.status}")
                return True, execute_response_text

    except asyncio.TimeoutError:
        await _log("❌ API request (aiohttp) timed out after 60s.")
        return False, "Permintaan ke API timeout setelah 60 detik."
    except aiohttp.ClientConnectorError as cerr:
        await _log(f"❌ API ClientConnectorError: {cerr}")
        return False, f"Error koneksi ke API: {str(cerr)}."
    except aiohttp.ClientError as cerr: 
        await _log(f"❌ API ClientError: {cerr}")
        return False, f"Error klien AIOHTTP: {str(cerr)}"
    except Exception as err: 
        print(f"--- Exception in send_freeze_droid_web_actual for target {target_number} ---")
        traceback.print_exc()
        print(f"--- End of exception ---")
        await _log(f"💥 General error during API call: {type(err).__name__} - {err}")
        return False, f"Error umum saat menghubungi API: {str(err)}"

# extract_status_info_web function remains the same as in the previous response.
# It's synchronous and does not need rate limiting itself.
def extract_status_info_web(html_content, target_number_fallback=None):
    try:
        if "Cannot POST /" in html_content and "<title>Error</title>" in html_content:
            path_error = re.search(r"Cannot POST (/\S+)", html_content)
            path_str = path_error.group(1) if path_error else "unknown path"
            return {
                'success': False,
                'message': f'Login API Gagal: URL ({path_str}) tidak ditemukan/salah metode.',
                'details': {'status': 'API Login Endpoint Error', 'target': target_number_fallback, 'info': f'URL login API ({path_str}) tidak ditemukan atau tidak menerima metode POST.', 'waktu': None}
            }

        if "<title>HASCLAW API Login</title>" in html_content or "Login akun anda" in html_content:
            return {
                'success': False,
                'message': 'Login API Gagal: Kredensial salah atau sesi habis.',
                'details': {'status': 'Authentication Required', 'target': target_number_fallback, 'info': 'API memerlukan login. Kredensial mungkin salah, sesi login gagal, atau sesi sudah habis.', 'waktu': None}
            }

        is_travas_form_page = "Travas Andros Execution" in html_content and \
                              ("Info: Masukkan nomor target" in html_content or "Masukkan nomor target (62xxxx)" in html_content)
        is_not_execution_result = "Status: Server ON" in html_content and not ("Status: S U C C E S !!" in html_content or '<div class="info">' in html_content)

        if is_travas_form_page and is_not_execution_result:
            return {
                'success': False,
                'message': 'API Error: Dikembalikan ke form input, target mungkin tidak diproses.',
                'details': {'status': 'API Returned Input Form', 'target': target_number_fallback, 'info': 'API mengembalikan form input target, bukan hasil eksekusi. Parameter target mungkin tidak diproses dengan benar atau sesi tidak valid.', 'waktu': None}
            }

        soup = BeautifulSoup(html_content, 'html.parser')
        info_div = soup.find('div', class_='info')

        if info_div:
            status, target, info, waktu = None, None, None, None
            for p_tag in info_div.find_all('p'):
                text = p_tag.get_text()
                if 'Status:' in text: status = text.split('Status:', 1)[1].strip()
                elif 'Target:' in text: target = text.split('Target:', 1)[1].strip()
                elif 'Info:' in text: info = text.split('Info:', 1)[1].strip()
                elif 'Waktu:' in text: waktu = text.split('Waktu:', 1)[1].strip()

            success_flag = False
            if status:
                status_lower = status.lower()
                success_keywords = ['s u c c e s', 'success', 'berhasil', 'sukses', 'execution', 'sent', 'delivered', 'terkirim', 'berjalan']
                failure_keywords = ['gagal', 'failed', 'error', 'limit', 'tidak valid', 'invalid']
                if any(keyword in status_lower for keyword in success_keywords) and \
                   not any(keyword in status_lower for keyword in failure_keywords):
                    success_flag = True
                if any(emoji in status for emoji in ['✅', '🧬', '⚡']):
                    success_flag = True
            
            if not success_flag and info:
                info_lower = info.lower()
                if ("execution" in info_lower or "hasclaw" in info_lower or "travas" in info_lower or "berhasil" in info_lower or "sukses" in info_lower) and \
                   not any(keyword in info_lower for keyword in failure_keywords):
                    success_flag = True

            title_tag = soup.find('title')
            if not success_flag and title_tag and \
               ('FreezeDroid API' in title_tag.get_text() or 'Execution Result' in title_tag.get_text()) and \
               status and target:
                success_flag = True
            
            final_target = target if target else target_number_fallback
            message = f"Status: {status or 'N/A'}, Info: {info or 'N/A'}"
            
            return {'success': success_flag, 
                    'message': message, 
                    'details': {'status': status, 'target': final_target, 'info': info, 'waktu': waktu}}

        html_lower = html_content.lower()
        if "s u c c e s !!" in html_lower or \
           ("hasclaw execution target" in html_lower and "status:" in html_lower and "target:" in html_lower):
            extracted_target_fb, extracted_status_fb, extracted_info_fb = None, None, None
            target_match_fb = re.search(r'target:\s*(\+?\d+)', html_lower)
            if target_match_fb: extracted_target_fb = target_match_fb.group(1).strip()
            else: extracted_target_fb = target_number_fallback

            status_match_fb = re.search(r'status:\s*([^\n<]+)', html_lower)
            if status_match_fb: extracted_status_fb = status_match_fb.group(1).strip().upper()
            else: extracted_status_fb = "Execution Success (Fallback)"

            info_match_fb = re.search(r'info:\s*([^\n<]+)', html_lower)
            if info_match_fb: extracted_info_fb = info_match_fb.group(1).strip()
            else: extracted_info_fb = "Request berhasil diproses (deteksi fallback)."
            
            message = f"Status: {extracted_status_fb}, Info: {extracted_info_fb}"
            return {
                'success': True, 'message': message,
                'details': {'status': extracted_status_fb, 'target': extracted_target_fb, 'info': extracted_info_fb, 'waktu': None}
            }

        return {
            'success': False,
            'message': 'Gagal Parsing: Format respons API tidak dikenal.',
            'details': {'status': 'Parse Error', 'target': target_number_fallback, 'info': 'Tidak dapat mengekstrak informasi status dari respons API.', 'waktu': None}
        }
    except Exception as e:
        print(f"--- Exception in extract_status_info_web ---")
        traceback.print_exc()
        print(f"--- End of exception ---")
        return {
            'success': False,
            'message': f'Gagal Parsing HTML: {type(e).__name__}', 
            'details': {'status': 'Parse Exception', 'target': target_number_fallback, 'info': f'Error internal saat parsing HTML: {str(e)}', 'waktu': None}
        }