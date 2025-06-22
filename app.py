# Monkey patching will be handled by Gunicorn when using -k gevent.
# from gevent import monkey
# monkey.patch_all(thread=False, signal=False)

import gevent
from gevent.queue import Queue as GeventQueue

from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, flash
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import asyncio
from datetime import datetime, date, timedelta # Pastikan datetime diimpor dari datetime
import time
import traceback
import json

load_dotenv()

from api_handler import send_freeze_droid_web_rate_limited, extract_status_info_web
from models import db, User, AdminSetting, PlanType, initialize_default_settings
from forms import LoginForm, AdminLoginForm, UserForm, AdminSettingsForm

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_flask_secret_CHANGE_ME")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///./freezedroid.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_SECRET_KEY'] = os.getenv("WTF_CSRF_SECRET_KEY", "default_csrf_secret_CHANGE_ME")

db.init_app(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = "info"
# login_manager.blueprint_login_views tidak perlu di-set lagi untuk admin_bp
# karena admin_login akan dihandle secara manual oleh session, bukan Flask-Login User

log_queue = GeventQueue()
progress_event_queue = GeventQueue()

API_CONFIG_LOADED = False
def check_api_config():
    global API_CONFIG_LOADED
    required_vars = ["API_USERNAME", "API_KEY", "API_BASE_URL", "API_LOGIN_ACTION_PATH", "API_EXECUTE_PATH"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"CRITICAL SERVER STARTUP ERROR: Missing API config vars: {', '.join(missing_vars)}")
        API_CONFIG_LOADED = False
    else:
        print("INFO: API Configuration seems to be loaded successfully at startup.")
        API_CONFIG_LOADED = True
    return API_CONFIG_LOADED

check_api_config()

ADMIN_USERNAME_ENV = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD_ENV = os.getenv("ADMIN_PASSWORD")
ADMIN_PATH_SECRET_ENV = os.getenv("ADMIN_PATH_SECRET", "default_admin_secret_path_CHANGE_ME") # Tambahkan default jika tidak ada

try:
    with app.app_context():
        print("INFO: Entering app context for DB initialization...")
        db.create_all()
        print("INFO: Database table creation process complete (or tables already existed).")
        print("INFO: Attempting to initialize default settings...")
        initialize_default_settings()
        print("INFO: Default settings initialization process complete.")
        print("INFO: Exited app context for DB initialization.")
except Exception as e_init:
    print(f"CRITICAL ERROR during DB initialization: {e_init}")
    traceback.print_exc()

@login_manager.user_loader
def load_user(user_id):
    if session.get('is_admin'): # Admin tidak dikelola oleh user_loader Flask-Login
        return None
    return User.query.get(int(user_id))

# >>> PERUBAHAN DIMULAI: Menambahkan context processor untuk tahun <<<
@app.context_processor
def inject_current_year():
    return {'current_year': datetime.utcnow().year}
# >>> PERUBAHAN SELESAI <<<

# ... (fungsi helper: run_asyncio_task_in_greenlet, log_message_sse_async, dll. tetap sama) ...
def run_asyncio_task_in_greenlet(async_coro, *args):
    def greenlet_body():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(async_coro(*args))
            return result
        except Exception as e:
            log_message_sse_sync(f"💥 [{datetime.now().strftime('%H:%M:%S')}] Error in background task ({async_coro.__name__}): {type(e).__name__} - {e}")
            progress_event_queue.put(json.dumps({"type": "task_error", "taskName": async_coro.__name__, "error": str(e)}))
            print(f"--- Error in greenlet_body ({async_coro.__name__} with args {args}) ---")
            traceback.print_exc()
            print(f"--- End of error ---")
        finally:
            if not loop.is_closed():
                tasks = asyncio.all_tasks(loop)
                if tasks:
                    for task in tasks:
                        if not task.done() and not task.cancelled():
                            task.cancel()
                    async def finalize_tasks():
                        await asyncio.gather(*tasks, return_exceptions=True)
                    loop.run_until_complete(finalize_tasks())
                loop.close()
            asyncio.set_event_loop(None)
    gevent.spawn(greenlet_body)

async def log_message_sse_async(message): log_queue.put(message)
def log_message_sse_sync(message): log_queue.put(message)
async def send_progress_update_async(progress_data): progress_event_queue.put(json.dumps(progress_data))


@app.route('/', methods=['GET'])
def landing_page():
    if current_user.is_authenticated and not session.get('is_admin'):
        return redirect(url_for('dashboard'))
    # Jika admin sudah login dan mencoba akses landing, arahkan ke admin dashboard
    if session.get('is_admin'):
        # Ambil path admin dari env untuk redirect yang benar
        admin_path = ADMIN_PATH_SECRET_ENV
        return redirect(f'/{admin_path.strip("/")}/dashboard') # Pastikan path bersih

    with app.app_context():
        trial_daily_limit = AdminSetting.get("trial_daily_limit", 10)
        trial_duration_days = AdminSetting.get("trial_duration_days", 3)
    return render_template('landing.html',
                           trial_daily_limit=trial_daily_limit,
                           trial_duration_days=trial_duration_days)

@app.route('/login', methods=['GET', 'POST'])
def login():
    # ... (fungsi login user tetap sama) ...
    if current_user.is_authenticated and not session.get('is_admin'):
        return redirect(url_for('dashboard'))
    if session.get('is_admin'):
        admin_path = ADMIN_PATH_SECRET_ENV
        return redirect(f'/{admin_path.strip("/")}/dashboard') # Pastikan path bersih
    if AdminSetting.get("maintenance_mode", False):
        flash('The application is currently under maintenance. Please try again later.', 'warning')
        return render_template('login.html', form=LoginForm(), maintenance=True)
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('Your account is inactive. Please contact support.', 'error')
                return redirect(url_for('login'))
            if user.is_expired:
                expiry_msg = f'Your account expired on {user.expiry_date.strftime("%Y-%m-%d")}.' if user.expiry_date else 'Your account has expired.'
                flash(f'{expiry_msg} Please renew your subscription or contact support.', 'error')
                return redirect(url_for('login'))
            login_user(user)
            session.pop('is_admin', None)
            log_message_sse_sync(f"👤 [{datetime.now().strftime('%H:%M:%S')}] User '{user.username}' logged in.")
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html', form=form, maintenance=False)


@app.route('/logout')
@login_required
def logout():
    # ... (fungsi logout user tetap sama) ...
    username = current_user.username if current_user.is_authenticated and hasattr(current_user, 'username') else "User"
    logout_user()
    log_message_sse_sync(f"👤 [{datetime.now().strftime('%H:%M:%S')}] {username} logged out.")
    flash('You have been logged out.', 'info')
    return redirect(url_for('landing_page'))

@app.route('/dashboard')
@login_required
def dashboard():
    # ... (fungsi dashboard user tetap sama, dengan variabel js_*) ...
    if AdminSetting.get("maintenance_mode", False):
        logout_user()
        flash('The application is under maintenance. You have been logged out.', 'warning')
        return redirect(url_for('login'))
    js_user_plan = current_user.plan.value if current_user.is_authenticated else "Unknown"
    js_is_trial_expired = False
    js_trial_requests_today = 0
    if current_user.is_authenticated:
        js_is_trial_expired = current_user.is_expired
        if current_user.plan.name == 'TRIAL':
            js_trial_requests_today = current_user.requests_today
    js_trial_daily_limit = AdminSetting.get('trial_daily_limit', 10)
    return render_template('index.html',
                           user_plan=current_user.plan.value,
                           js_user_plan=js_user_plan,
                           js_is_trial_expired=js_is_trial_expired,
                           js_trial_requests_today=js_trial_requests_today,
                           js_trial_daily_limit=js_trial_daily_limit)


# ... (rute crash_single_web, crash_multi_web, dan fungsi async helper tetap sama) ...
# (Untuk singkatnya, saya tidak akan menyalin semua fungsi ini lagi di sini)
async def actual_single_crash_processing(target_number, user_id):
    user = None
    with app.app_context():
      user = User.query.get(user_id)
    if not user:
        await log_message_sse_async(f"❌ [{datetime.now().strftime('%H:%M:%S')}] Target {target_number}: User {user_id} not found for task.")
        await send_progress_update_async({"type": "single_result", "target": target_number, "success": False, "message": "User not found for task."})
        return
    if not API_CONFIG_LOADED:
        await log_message_sse_async(f"❌ [{datetime.now().strftime('%H:%M:%S')}] Target {target_number} (User: {user.username}): Aborted. API config missing.")
        await send_progress_update_async({"type": "single_result", "target": target_number, "success": False, "message": "Server API config missing."})
        return
    await log_message_sse_async(f"⏳ [{datetime.now().strftime('%H:%M:%S')}] BG task for target {target_number} (User: {user.username})...")
    await send_progress_update_async({"type": "single_status", "target": target_number, "status_message": "Processing...", "success": None})
    try:
        api_call_successful, result_data = await send_freeze_droid_web_rate_limited(target_number, log_callback=log_message_sse_async)
        if api_call_successful:
            parsed_info = extract_status_info_web(result_data, target_number_fallback=target_number)
            await log_message_sse_async(f"📊 [{datetime.now().strftime('%H:%M:%S')}] Single Crash Result for {target_number} (User: {user.username}): {parsed_info['message']}")
            await send_progress_update_async({
                "type": "single_result",
                "target": parsed_info.get('details', {}).get('target', target_number),
                "success": parsed_info['success'],
                "message": parsed_info['message'],
                "details_status": parsed_info.get('details', {}).get('status'),
                "details_info": parsed_info.get('details', {}).get('info')
            })
        else:
            await log_message_sse_async(f"⚠️ [{datetime.now().strftime('%H:%M:%S')}] Single Crash Failed (API Call to {target_number}, User: {user.username}): {result_data}")
            await send_progress_update_async({"type": "single_result", "target": target_number, "success": False, "message": f"API Call Failed: {result_data}"})
    except Exception as e:
        await log_message_sse_async(f"💥 [{datetime.now().strftime('%H:%M:%S')}] Exception in single crash for {target_number} (User: {user.username}): {type(e).__name__}")
        await send_progress_update_async({"type": "single_result", "target": target_number, "success": False, "message": f"Error: {type(e).__name__}"})
        print(f"--- Exception in actual_single_crash_processing for {target_number} (User: {user.username}) ---")
        traceback.print_exc()
        print(f"--- End of exception ---")

@app.route('/web/crash-single', methods=['POST'])
@login_required
def crash_single_web():
    if AdminSetting.get("maintenance_mode", False): return jsonify({"success": False, "error": "Application under maintenance"}), 503
    if current_user.plan not in [PlanType.TRIAL, PlanType.SINGLE, PlanType.MULTI]: return jsonify({"success": False, "error": "Your current plan does not allow this action."}), 403
    if current_user.is_expired: return jsonify({"success": False, "error": "Your account has expired."}), 403
    target_number = request.form.get('target_number')
    if not target_number or not target_number.isdigit(): return jsonify({"success": False, "error": "Invalid target number"}), 400
    if not API_CONFIG_LOADED: return jsonify({"success": False, "error": "Server API configuration error. Contact admin."}), 500
    if current_user.plan == PlanType.TRIAL:
        trial_limit = AdminSetting.get("trial_daily_limit", 10)
        today = date.today()
        if current_user.last_request_date != today:
            current_user.requests_today = 0
            current_user.last_request_date = today
        if current_user.requests_today >= trial_limit: return jsonify({"success": False, "error": f"Trial daily limit of {trial_limit} requests reached."}), 429
        current_user.requests_today += 1
        db.session.commit()
    log_message_sse_sync(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] Single Crash (User: {current_user.username}): Request received for {target_number}. Processing in background...")
    progress_event_queue.put(json.dumps({"type": "single_status", "target": target_number, "status_message": "Request sent to server...", "success": None}))
    run_asyncio_task_in_greenlet(actual_single_crash_processing, target_number, current_user.id)
    return jsonify({"success": True, "status": "processing", "message": f"Request for {target_number} received. Check logs and UI for updates."}), 202

async def actual_multi_crash_processing(target_numbers, original_filename, user_id):
    user = None
    with app.app_context(): user = User.query.get(user_id)
    if not user:
        await log_message_sse_async(f"❌ File '{original_filename}': User {user_id} not found.")
        await send_progress_update_async({"type": "multi_complete", "filename": original_filename, "total": len(target_numbers), "success_count": 0, "failure_count": len(target_numbers), "error": "User not found."})
        return
    if not API_CONFIG_LOADED:
        await log_message_sse_async(f"❌ File '{original_filename}' (User: {user.username}): Aborted. API config missing.")
        await send_progress_update_async({"type": "multi_complete", "filename": original_filename, "total": len(target_numbers), "success_count": 0, "failure_count": len(target_numbers), "error": "API config missing."})
        return
    await log_message_sse_async(f"⏳ BG multi-crash for '{original_filename}' (User: {user.username}, {len(target_numbers)} targets) started...")
    await send_progress_update_async({"type": "multi_start", "filename": original_filename, "total_targets": len(target_numbers)})
    overall_success_count = 0; overall_failure_count = 0
    for i, target_number in enumerate(target_numbers):
        await send_progress_update_async({"type": "multi_progress_item_start", "filename": original_filename, "current_index": i + 1, "total_targets": len(target_numbers), "target_number": target_number})
        await log_message_sse_async(f"⏳ Multi Crash (User: {user.username}, {i+1}/{len(target_numbers)} of '{original_filename}'): Processing {target_number}...")
        success_flag_item = False; message_item = "Unknown error"
        try:
            api_call_successful, result_data = await send_freeze_droid_web_rate_limited(target_number, log_callback=log_message_sse_async)
            if api_call_successful:
                parsed_info = extract_status_info_web(result_data, target_number_fallback=target_number)
                await log_message_sse_async(f"📊 Multi Crash Item Result for {target_number} (from '{original_filename}', User: {user.username}): {parsed_info['message']}")
                success_flag_item = parsed_info['success']; message_item = parsed_info['message']
            else:
                await log_message_sse_async(f"⚠️ Multi Crash Item Failed (API Call) for {target_number} (from '{original_filename}', User: {user.username}): {result_data}")
                message_item = f"API Call Failed: {result_data}"
        except Exception as e_inner:
            await log_message_sse_async(f"💥 Exception for target {target_number} in multi-crash ('{original_filename}', User: {user.username}): {type(e_inner).__name__}")
            message_item = f"Error: {type(e_inner).__name__}"
            print(f"--- Exception in actual_multi_crash_processing item for {target_number} (User: {user.username}) ---"); traceback.print_exc(); print(f"--- End of exception ---")
        if success_flag_item: overall_success_count += 1
        else: overall_failure_count += 1
        await send_progress_update_async({"type": "multi_progress_item_result", "filename": original_filename, "current_index": i + 1, "total_targets": len(target_numbers), "target_number": target_number, "success": success_flag_item, "message": message_item, "current_success_count": overall_success_count, "current_failure_count": overall_failure_count})
        await asyncio.sleep(0.01); gevent.sleep(0.1)
    final_summary_msg = f"🏁 Multi Crash Complete for '{original_filename}' (User: {user.username}). Total: {len(target_numbers)}, Success: {overall_success_count}, Failure: {overall_failure_count}."
    await log_message_sse_async(final_summary_msg)
    await send_progress_update_async({"type": "multi_complete", "filename": original_filename, "total": len(target_numbers), "success_count": overall_success_count, "failure_count": overall_failure_count, "summary_message": final_summary_msg})

@app.route('/web/crash-multi', methods=['POST'])
@login_required
def crash_multi_web():
    if AdminSetting.get("maintenance_mode", False): return jsonify({"success": False, "error": "Application under maintenance"}), 503
    if current_user.plan != PlanType.MULTI: return jsonify({"success": False, "error": "Your current plan does not allow multi-target crashes."}), 403
    if current_user.is_expired: return jsonify({"success": False, "error": "Your account has expired."}), 403
    if 'target_file' not in request.files: return jsonify({"success": False, "error": "No file part"}), 400
    file = request.files['target_file']
    if file.filename == '': return jsonify({"success": False, "error": "No selected file"}), 400
    if not API_CONFIG_LOADED: return jsonify({"success": False, "error": "Server API configuration error. Contact admin."}), 500
    if file and file.filename.endswith('.txt'):
        try:
            content = file.read().decode('utf-8')
            target_numbers = [line.strip() for line in content.splitlines() if line.strip().isdigit()]
        except Exception as e: return jsonify({"success": False, "error": f"Error reading file: {str(e)}"}), 400
        if not target_numbers: return jsonify({"success": False, "error": "No valid numbers found in file."}), 400
        log_message_sse_sync(f"🚀 Multi Crash (User: {current_user.username}): Request for '{file.filename}'. Processing {len(target_numbers)} targets...")
        progress_event_queue.put(json.dumps({"type": "multi_status", "filename": file.filename, "status_message": "Request sent, preparing tasks..."}))
        run_asyncio_task_in_greenlet(actual_multi_crash_processing, target_numbers, file.filename, current_user.id)
        return jsonify({"success": True, "status": "processing", "message": f"Request for file '{file.filename}' received."}), 202
    else: return jsonify({"success": False, "error": "Invalid file type. Upload .txt."}), 400

@app.route('/stream-logs')
def stream_logs():
    # ... (fungsi stream_logs tetap sama) ...
    is_admin_session = session.get('is_admin', False)
    if not (current_user.is_authenticated or is_admin_session):
         return Response("Not authenticated", status=401)
    def generate_events_with_better_keepalive():
        try:
            yield "event: connection_established\ndata: Log stream connected to server (v3).\n\n"
            last_keep_alive_time = time.monotonic()
            while True:
                item_found = False
                try:
                    message = log_queue.get(block=False)
                    yield f"event: log_message\ndata: {json.dumps(str(message))}\n\n"
                    item_found = True; last_keep_alive_time = time.monotonic()
                except gevent.queue.Empty: pass
                try:
                    progress_json_str = progress_event_queue.get(block=False)
                    yield f"event: progress_update\ndata: {progress_json_str}\n\n"
                    item_found = True; last_keep_alive_time = time.monotonic()
                except gevent.queue.Empty: pass
                current_time = time.monotonic()
                if (current_time - last_keep_alive_time) > 20:
                    yield "event: keep-alive\ndata: \n\n"; last_keep_alive_time = current_time
                if not item_found: gevent.sleep(0.1)
        except GeneratorExit: pass
        except Exception as e_stream:
             print(f"--- Unhandled error in SSE stream: {e_stream} ---"); traceback.print_exc()
    return Response(generate_events_with_better_keepalive(), mimetype='text/event-stream')


# --- Registrasi Blueprint Admin ---
from admin import admin_bp
# Gunakan ADMIN_PATH_SECRET_ENV untuk url_prefix blueprint admin
# Pastikan ADMIN_PATH_SECRET_ENV tidak dimulai dengan '/' jika Anda menambahkannya secara manual
# dan pastikan tidak ada '//' ganda.
# Lebih aman untuk memastikan path bersih:
clean_admin_path = f"/{ADMIN_PATH_SECRET_ENV.strip('/')}"
app.register_blueprint(admin_bp, url_prefix=clean_admin_path)
print(f"INFO: Admin blueprint registered at {clean_admin_path}")


if __name__ == '__main__':
    if "gunicorn" not in os.environ.get("SERVER_SOFTWARE", "").lower():
        print("INFO: Applying gevent monkey patches for local 'python app.py' run.")
        from gevent import monkey
        monkey.patch_all(thread=False, signal=False)

    if not ADMIN_USERNAME_ENV or not ADMIN_PASSWORD_ENV:
        print("CRITICAL ERROR: ADMIN_USERNAME and/or ADMIN_PASSWORD environment variables not set.")
        exit(1)
    if not ADMIN_PATH_SECRET_ENV or ADMIN_PATH_SECRET_ENV == "default_admin_secret_path_CHANGE_ME":
        print("CRITICAL ERROR: ADMIN_PATH_SECRET environment variable not set or is default. Set a strong random path.")
        exit(1)
    if not API_CONFIG_LOADED:
         print("CRITICAL WARNING: API configuration is missing or incomplete. API-dependent features will fail.")

    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    port = int(os.getenv("PORT", 5000))

    print("---------------------------------------------------------------------")
    print("FreezeDroid Web Application Starting...")
    print(f"Flask Debug Mode: {'ON' if debug_mode else 'OFF'}")
    print(f"Admin Panel will be at: /{ADMIN_PATH_SECRET_ENV.strip('/')}/login (atau path dashboard setelah login)")
    print(f"Listening on Port: {port}")
    print("ALERT: To run with Gunicorn (recommended for production-like testing):")
    print(f"       gunicorn -k gevent app:app --bind 0.0.0.0:{port} --workers ${{WEB_CONCURRENCY:-2}} --timeout 120 --access-logfile - --error-logfile - --log-level debug")
    if debug_mode:
        print("       (Consider adding --reload for Gunicorn auto-reload during development)")
    print("---------------------------------------------------------------------")

    if "gunicorn" in os.environ.get("SERVER_SOFTWARE", "").lower():
        print(f"INFO: Running under Gunicorn. Flask's app.run() will not be called by this __main__ block.")
    else:
        print(f"INFO: Running Flask development server (not Gunicorn) on http://0.0.0.0:{port}")
        app.run(debug=debug_mode, host='0.0.0.0', port=port, use_reloader=debug_mode)