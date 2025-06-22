// static/js/script.js
document.addEventListener('DOMContentLoaded', function () {
    const serverDataElement = document.getElementById('server-data');
    let serverData = {};
    if (serverDataElement) {
        try {
            serverData = JSON.parse(serverDataElement.textContent);
        } catch (e) {
            console.error("Error parsing server data:", e);
        }
    }

    const singleCrashForm = document.getElementById('singleCrashForm');
    const multiCrashForm = document.getElementById('multiCrashForm');
    const logsOutput = document.getElementById('logsOutput');
    const loadingIndicator = document.getElementById('loading-indicator');
    const singleTargetFeedback = document.getElementById('singleTargetFeedback');
    const multiTargetFeedback = document.getElementById('multiTargetFeedback');
    const multiTargetProgressBarContainer = document.getElementById('multiTargetProgressBarContainer');
    const multiTargetProgressBar = document.getElementById('multiTargetProgressBar');

    // >>> PERUBAHAN DIMULAI: Fungsi untuk menonaktifkan/mengaktifkan tombol <<<
    function setButtonState(button, isLoading) {
        if (button) {
            button.disabled = isLoading;
            if (isLoading) {
                button.innerHTML = '<div class="spinner" style="width:16px; height:16px; border-width:2px; margin-right:8px;"></div> Processing...';
            } else {
                // Kembalikan teks asli tombol
                if (button.closest('form').id === 'singleCrashForm') {
                    button.innerHTML = '<i class="fas fa-rocket"></i> Launch Attack';
                } else if (button.closest('form').id === 'multiCrashForm') {
                    button.innerHTML = '<i class="fas fa-network-wired"></i> Launch Barrage';
                }
            }
        }
    }
    // >>> PERUBAHAN SELESAI <<<

    function appendLog(message, type = 'info') {
        if (!logsOutput) return;
        const time = new Date().toLocaleTimeString();
        const logEntry = document.createElement('div');
        logEntry.innerHTML = `[${time}] ${message.replace(/</g, "<").replace(/>/g, ">")}`; // Basic XSS prevention
        logEntry.classList.add('log-entry', `log-${type}`);
        logsOutput.appendChild(logEntry);
        logsOutput.scrollTop = logsOutput.scrollHeight;
        if (loadingIndicator) loadingIndicator.style.display = 'none';
    }

    function updateFeedback(element, message, success) {
        if (!element) return;
        element.textContent = message;
        element.classList.remove('success', 'error');
        if (success === true) {
            element.classList.add('success');
        } else if (success === false) {
            element.classList.add('error');
        }
    }

    if (singleCrashForm) {
        singleCrashForm.addEventListener('submit', function (event) {
            event.preventDefault();
            if (loadingIndicator) loadingIndicator.style.display = 'flex';
            const targetNumberInput = document.getElementById('target_number');
            const targetNumber = targetNumberInput.value;
            const submitButton = singleCrashForm.querySelector('button[type="submit"]'); // >>> PERUBAHAN: Dapatkan tombol submit <<<

            if (!targetNumber) {
                updateFeedback(singleTargetFeedback, "Target number cannot be empty.", false);
                if (loadingIndicator) loadingIndicator.style.display = 'none';
                return;
            }

            // >>> PERUBAHAN DIMULAI: Nonaktifkan tombol <<<
            setButtonState(submitButton, true);
            // >>> PERUBAHAN SELESAI <<<

            updateFeedback(singleTargetFeedback, `Sending request for ${targetNumber}...`, null);
            appendLog(`🚀 Sending single crash request for ${targetNumber}...`);

            const formData = new FormData(singleCrashForm);

            fetch('/web/crash-single', {
                method: 'POST',
                body: formData,
                headers: {
                    // CSRF token in FormData is usually sufficient for Flask-WTF if name is 'csrf_token'
                    // 'X-CSRFToken': formData.get('csrf_token') // Atau ambil dari input hidden jika ada masalah
                }
            })
            .then(response => {
                // >>> PERUBAHAN DIMULAI: Penanganan respons yang lebih baik <<<
                if (!response.ok) {
                    // Mencoba membaca body error jika ada
                    return response.json().catch(() => ({ // Jika body bukan JSON atau kosong
                        success: false, 
                        error: `Server error: ${response.status} ${response.statusText}`
                    })).then(errData => {
                        throw errData; // Lemparkan data error yang sudah diproses
                    });
                }
                return response.json();
                // >>> PERUBAHAN SELESAI <<<
            })
            .then(data => {
                if (data.success) {
                    // Feedback awal, update lebih lanjut via SSE
                    updateFeedback(singleTargetFeedback, data.message || `Request for ${targetNumber} sent. Waiting for SSE...`, true);
                } else {
                    updateFeedback(singleTargetFeedback, data.error || "An unknown error occurred.", false);
                    appendLog(`❌ Error submitting single crash for ${targetNumber}: ${data.error || 'Unknown error'}`, 'error');
                }
            })
            .catch(error => {
                console.error('Fetch Error (Single Crash):', error);
                // >>> PERUBAHAN DIMULAI: Menampilkan error.message jika ada <<<
                const errorMessage = error.error || error.message || "Network error or server unavailable.";
                updateFeedback(singleTargetFeedback, `Error: ${errorMessage}`, false);
                appendLog(`💥 Fetch Error (Single Crash): ${errorMessage}`, 'error');
                // >>> PERUBAHAN SELESAI <<<
            })
            .finally(() => {
                if (loadingIndicator) loadingIndicator.style.display = 'none';
                 // >>> PERUBAHAN DIMULAI: Aktifkan kembali tombol <<<
                setButtonState(submitButton, false);
                // >>> PERUBAHAN SELESAI <<<
                if (targetNumberInput) targetNumberInput.value = ''; // Kosongkan input setelah submit
            });
        });
    }

    if (multiCrashForm) {
        multiCrashForm.addEventListener('submit', function (event) {
            event.preventDefault();
            if (loadingIndicator) loadingIndicator.style.display = 'flex';
            const fileInput = document.getElementById('target_file');
            const submitButton = multiCrashForm.querySelector('button[type="submit"]'); // >>> PERUBAHAN: Dapatkan tombol submit <<<


            if (!fileInput.files || fileInput.files.length === 0) {
                updateFeedback(multiTargetFeedback, "Please select a .txt file.", false);
                if (loadingIndicator) loadingIndicator.style.display = 'none';
                return;
            }

             // >>> PERUBAHAN DIMULAI: Nonaktifkan tombol <<<
            setButtonState(submitButton, true);
            // >>> PERUBAHAN SELESAI <<<

            updateFeedback(multiTargetFeedback, `Uploading ${fileInput.files[0].name}...`, null);
            appendLog(`🚀 Uploading file ${fileInput.files[0].name} for multi-crash...`);
            if (multiTargetProgressBarContainer) multiTargetProgressBarContainer.style.display = 'none';
            if (multiTargetProgressBar) multiTargetProgressBar.style.width = '0%';


            const formData = new FormData(multiCrashForm);

            fetch('/web/crash-multi', {
                method: 'POST',
                body: formData,
                 headers: {
                    // CSRF token in FormData
                }
            })
            .then(response => {
                 // >>> PERUBAHAN DIMULAI: Penanganan respons yang lebih baik <<<
                if (!response.ok) {
                    return response.json().catch(() => ({
                        success: false,
                        error: `Server error: ${response.status} ${response.statusText}`
                    })).then(errData => {
                        throw errData;
                    });
                }
                return response.json();
                // >>> PERUBAHAN SELESAI <<<
            })
            .then(data => {
                if (data.success) {
                    updateFeedback(multiTargetFeedback, data.message || `File ${fileInput.files[0].name} uploaded. Waiting for SSE...`, true);
                } else {
                    updateFeedback(multiTargetFeedback, data.error || "An unknown error occurred during upload.", false);
                    appendLog(`❌ Error submitting multi crash for ${fileInput.files[0].name}: ${data.error || 'Unknown error'}`, 'error');
                }
            })
            .catch(error => {
                console.error('Fetch Error (Multi Crash):', error);
                 // >>> PERUBAHAN DIMULAI: Menampilkan error.message jika ada <<<
                const errorMessage = error.error || error.message || "Network error or server unavailable.";
                updateFeedback(multiTargetFeedback, `Error: ${errorMessage}`, false);
                appendLog(`💥 Fetch Error (Multi Crash): ${errorMessage}`, 'error');
                 // >>> PERUBAHAN SELESAI <<<
            })
            .finally(() => {
                if (loadingIndicator) loadingIndicator.style.display = 'none';
                 // >>> PERUBAHAN DIMULAI: Aktifkan kembali tombol <<<
                setButtonState(submitButton, false);
                // >>> PERUBAHAN SELESAI <<<
                if (fileInput) fileInput.value = ''; // Reset file input
            });
        });
    }

    // SSE (Server-Sent Events)
    const eventSource = new EventSource('/stream-logs');

    eventSource.onopen = function() {
        console.log("SSE connection established.");
        appendLog("🔌 Log stream connected to server.", 'system');
    };

    eventSource.addEventListener('log_message', function (event) {
        try {
            const messageData = JSON.parse(event.data);
            appendLog(messageData);
        } catch (e) {
            appendLog(event.data); // Fallback for non-JSON
        }
    });

    eventSource.addEventListener('progress_update', function (event) {
        try {
            const progressData = JSON.parse(event.data);
            // console.log("SSE Progress:", progressData);

            if (progressData.type === "single_status" || progressData.type === "single_result") {
                updateFeedback(singleTargetFeedback, progressData.message || progressData.status_message, progressData.success);
                if (progressData.type === "single_result") {
                     appendLog(`[Target: ${progressData.target}] ${progressData.success ? '✅' : '❌'} ${progressData.message}`);
                }
            } else if (progressData.type === "multi_start") {
                updateFeedback(multiTargetFeedback, `Processing ${progressData.filename} (${progressData.total_targets} targets)...`, null);
                if (multiTargetProgressBarContainer) multiTargetProgressBarContainer.style.display = 'block';
                if (multiTargetProgressBar) multiTargetProgressBar.style.width = '0%';
                appendLog(`[File: ${progressData.filename}] Multi-crash started for ${progressData.total_targets} targets.`);
            } else if (progressData.type === "multi_progress_item_start") {
                const progress = (progressData.current_index / progressData.total_targets) * 100;
                if (multiTargetProgressBar) multiTargetProgressBar.style.width = `${progress}%`;
                updateFeedback(multiTargetFeedback, `File ${progressData.filename}: Processing ${progressData.target_number} (${progressData.current_index}/${progressData.total_targets})...`, null);
            } else if (progressData.type === "multi_progress_item_result") {
                 const progress = (progressData.current_index / progressData.total_targets) * 100;
                if (multiTargetProgressBar) multiTargetProgressBar.style.width = `${progress}%`;
                let itemMessage = `[File: ${progressData.filename}, Target: ${progressData.target_number}] ${progressData.success ? '✅' : '❌'} ${progressData.message}`;
                appendLog(itemMessage);
                // Feedback tetap menunjukkan progres keseluruhan
                updateFeedback(multiTargetFeedback, `File ${progressData.filename}: ${progressData.current_success_count} success, ${progressData.current_failure_count} fail of ${progressData.total_targets}`, null);

            } else if (progressData.type === "multi_complete") {
                if (multiTargetProgressBar) multiTargetProgressBar.style.width = '100%';
                updateFeedback(multiTargetFeedback, progressData.summary_message || `File ${progressData.filename} processed. Success: ${progressData.success_count}, Fail: ${progressData.failure_count}.`, progressData.success_count > 0 && progressData.failure_count === 0);
                appendLog(progressData.summary_message || `🏁 Multi-crash for ${progressData.filename} complete.`);
                // setTimeout(() => { // Sembunyikan progress bar setelah beberapa detik
                //    if (multiTargetProgressBarContainer) multiTargetProgressBarContainer.style.display = 'none';
                // }, 5000);
            } else if (progressData.type === "multi_status") {
                 updateFeedback(multiTargetFeedback, progressData.status_message, null);
            } else if (progressData.type === "task_error") {
                const taskName = progressData.taskName || "Background task";
                const errorMsg = progressData.error || "Unknown error";
                appendLog(`💥 Error in ${taskName}: ${errorMsg}`, 'error');
                // Tentukan feedback mana yang diupdate berdasarkan nama task jika ada
                if (taskName.includes("single")) {
                    updateFeedback(singleTargetFeedback, `Error in task: ${errorMsg}`, false);
                } else if (taskName.includes("multi")) {
                    updateFeedback(multiTargetFeedback, `Error in task: ${errorMsg}`, false);
                }
            }


        } catch (e) {
            console.error("Error processing SSE progress_update:", e, "Data:", event.data);
            appendLog("Error processing progress update from server.", 'error');
        }
    });

    eventSource.onerror = function (err) {
        console.error("SSE Error:", err);
        appendLog("⚠️ Log stream connection error or closed by server.", 'error');
        if (eventSource.readyState === EventSource.CLOSED) {
            appendLog("Connection closed. Attempting to reconnect in 5s...", "warning");
            // Gunicorn mungkin menutup koneksi idle, atau server restart.
            // Tidak perlu reconnect manual, browser biasanya akan mencoba.
        }
        // eventSource.close(); // Hentikan jika tidak ingin reconnect otomatis
    };

    // Update footer year
    const currentYearSpan = document.getElementById('currentYear');
    if (currentYearSpan) {
        currentYearSpan.textContent = new Date().getFullYear();
    }
});