/**
 * AutoTicket Web Management System - Frontend JavaScript Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- Global Config ---
    const API_BASE = '/tickekan-system/api';

    // --- Global State ---
    let eventSource = null;
    let autoScroll = true;
    let currentStatus = { is_running: false, is_waiting_input: false };

    // --- DOM Elements ---
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    const activeTabTitle = document.getElementById('active-tab-title');
    const activeTabDesc = document.getElementById('active-tab-desc');

    const globalStatusDot = document.getElementById('global-status-dot');
    const globalStatusText = document.getElementById('global-status-text');

    const btnRun = document.getElementById('btn-run');
    const btnHeaderRun = document.getElementById('btn-header-run');
    const btnStop = document.getElementById('btn-stop');

    const r7InputBanner = document.getElementById('r7-input-banner');
    const r7PromptMessage = document.getElementById('r7-prompt-message');
    const r7InputContainer = document.getElementById('r7-input-container');
    const r7InputStatusBadge = document.getElementById('r7-input-status-badge');
    const r7UrlInput = document.getElementById('r7-url-input');
    const btnSubmitUrl = document.getElementById('btn-submit-url');

    const terminalJobStatus = document.getElementById('terminal-job-status');
    const statusBadgeDot = document.getElementById('status-badge-dot');
    const statusBadgeText = document.getElementById('status-badge-text');
    const lastRunStatusText = document.getElementById('last-run-status-text');

    // --- Tab Navigation ---
    const tabMeta = {
        'tab-console': { title: '実行コントロール', desc: 'AutoTicket の手動実行・ステータス監視・R7ログイン対話入力' },
        'tab-env': { title: '.env 環境変数エディタ', desc: '項目名は固定保護されています。設定値 (Value) を更新してください' },
        'tab-account': { title: 'サービスアカウント設定', desc: 'Google Sheets API 連携用 service_account.json の管理' },
        'tab-cron': { title: '定期実行 (Cron) システム', desc: 'レンタルサーバー環境での自動実行タイミングの設定とステータス' },
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            navItems.forEach(n => n.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            item.classList.add('active');
            document.getElementById(targetTab).classList.add('active');

            if (tabMeta[targetTab]) {
                activeTabTitle.textContent = tabMeta[targetTab].title;
                activeTabDesc.textContent = tabMeta[targetTab].desc;
            }

            // Load data when tab opens
            if (targetTab === 'tab-env') loadEnvFields();
            if (targetTab === 'tab-account') loadServiceAccountStatus();
            if (targetTab === 'tab-cron') loadCronStatus();
        });
    });

    // --- Toast Notifications ---
    window.showToast = function (message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let icon = 'fa-circle-info';
        if (type === 'success') icon = 'fa-circle-check';
        if (type === 'error') icon = 'fa-circle-exclamation';

        toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    };

    // --- Copy Snippet Helper ---
    window.copyToClipboard = function (elementId) {
        const text = document.getElementById(elementId).textContent;
        navigator.clipboard.writeText(text).then(() => {
            showToast('クリップボードにコピーしました！', 'success');
        }).catch(err => {
            showToast('コピーに失敗しました', 'error');
        });
    };

    // --- Lightweight Status Polling ---
    let isPollingActive = false;

    function startPollingMode() {
        if (isPollingActive) return;
        isPollingActive = true;

        const poll = () => {
            fetch(`${API_BASE}/execution/status`)
                .then(res => res.json())
                .then(data => {
                    if (data.success && data.status) {
                        updateStatus(data.status);
                    }
                })
                .catch(err => console.error('Status polling error:', err))
                .finally(() => {
                    const interval = (currentStatus && (currentStatus.is_running || currentStatus.is_waiting_input)) ? 1000 : 2500;
                    setTimeout(poll, interval);
                });
        };
        poll();
    }

    function escapeHtml(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function updateStatus(status) {
        if (!status) return;
        currentStatus = status;

        // Global & Card status dot & text
        globalStatusDot.className = 'status-dot';
        if (statusBadgeDot) statusBadgeDot.className = 'status-dot';

        if (status.is_waiting_input) {
            globalStatusDot.classList.add('waiting');
            if (statusBadgeDot) statusBadgeDot.classList.add('waiting');
            globalStatusText.textContent = 'R7 URL入力待ち';
            if (statusBadgeText) statusBadgeText.textContent = 'R7 URL入力待ち';
            if (terminalJobStatus) {
                terminalJobStatus.textContent = 'WAITING FOR INPUT';
                terminalJobStatus.style.color = '#f59e0b';
            }
        } else if (status.is_running) {
            globalStatusDot.classList.add('running');
            if (statusBadgeDot) statusBadgeDot.classList.add('running');
            globalStatusText.textContent = 'AutoTicket 実行中...';
            if (statusBadgeText) statusBadgeText.textContent = 'AutoTicket 実行中...';
            if (terminalJobStatus) {
                terminalJobStatus.textContent = 'RUNNING';
                terminalJobStatus.style.color = '#10b981';
            }
        } else {
            globalStatusDot.classList.add('idle');
            if (statusBadgeDot) statusBadgeDot.classList.add('idle');
            globalStatusText.textContent = '待機中 (' + (status.last_run_status || '未実行') + ')';
            if (statusBadgeText) statusBadgeText.textContent = '待機中 (' + (status.last_run_status || '未実行') + ')';
            if (terminalJobStatus) {
                terminalJobStatus.textContent = status.last_run_status || 'IDLE';
                terminalJobStatus.style.color = '#94a3b8';
            }
        }

        if (lastRunStatusText) {
            lastRunStatusText.textContent = status.last_run_status || '未実行';
        }

        // Action buttons state
        if (btnRun) btnRun.disabled = status.is_running;
        if (btnHeaderRun) btnHeaderRun.disabled = status.is_running;
        if (btnStop) btnStop.disabled = !status.is_running;

        // Dynamic R7 Input Form Visibility (Hidden until input is required!)
        if (status.is_waiting_input) {
            if (r7InputBanner) {
                r7InputBanner.classList.remove('hidden');
                if (status.input_prompt) {
                    r7PromptMessage.textContent = status.input_prompt;
                }
            }
            if (r7InputContainer) {
                r7InputContainer.classList.remove('hidden');
                r7InputContainer.classList.add('active');
            }
            if (r7InputStatusBadge) {
                r7InputStatusBadge.className = 'badge badge-active';
                r7InputStatusBadge.textContent = 'URL入力が必要です！';
            }
            if (r7UrlInput) {
                r7UrlInput.disabled = false;
                r7UrlInput.focus();
            }
            if (btnSubmitUrl) btnSubmitUrl.disabled = false;
        } else {
            if (r7InputBanner) r7InputBanner.classList.add('hidden');
            if (r7InputContainer) {
                r7InputContainer.classList.add('hidden');
                r7InputContainer.classList.remove('active');
            }
            if (r7InputStatusBadge) {
                r7InputStatusBadge.className = 'badge badge-inactive';
                r7InputStatusBadge.textContent = '入力不要';
            }
            if (r7UrlInput) r7UrlInput.disabled = true;
            if (btnSubmitUrl) btnSubmitUrl.disabled = true;
        }
    }

    // --- Execution Controls ---
    function runAutoTicket() {
        // 開始ボタンを押すとすぐに実行中状態にする
        updateStatus({
            is_running: true,
            is_waiting_input: false,
            last_run_status: '実行中'
        });

        fetch(`${API_BASE}/execution/run`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showToast('AutoTicket の実行を開始しました', 'success');
                } else {
                    showToast(data.message || '実行に失敗しました', 'error');
                    // 失敗時は最新ステータスを即取得
                    fetch(`${API_BASE}/execution/status`)
                        .then(r => r.json())
                        .then(d => { if (d.status) updateStatus(d.status); });
                }
            })
            .catch(() => {
                showToast('サーバー通信エラー', 'error');
                fetch(`${API_BASE}/execution/status`)
                    .then(r => r.json())
                    .then(d => { if (d.status) updateStatus(d.status); });
            });
    }

    function stopAutoTicket() {
        fetch(`${API_BASE}/execution/stop`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showToast('プロセス停止要求を送信しました', 'info');
                } else {
                    showToast(data.message || '停止に失敗しました', 'error');
                }
            });
    }

    function submitR7Url() {
        const inputVal = r7UrlInput.value.trim();
        if (!inputVal) {
            showToast('URLまたはコードを入力してください', 'error');
            return;
        }

        fetch(`${API_BASE}/execution/input`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input: inputVal })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showToast('URLをプロセスへ送信しました！', 'success');
                r7UrlInput.value = '';
            } else {
                showToast(data.message || '送信エラー', 'error');
            }
        })
        .catch(() => showToast('送信時通信エラー', 'error'));
    }

    if (btnRun) btnRun.addEventListener('click', runAutoTicket);
    if (btnHeaderRun) btnHeaderRun.addEventListener('click', runAutoTicket);
    if (btnStop) btnStop.addEventListener('click', stopAutoTicket);

    if (btnSubmitUrl) btnSubmitUrl.addEventListener('click', submitR7Url);
    if (r7UrlInput) {
        r7UrlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !btnSubmitUrl.disabled) {
                submitR7Url();
            }
        });
    }

    // --- 1. .env Editor Logic ---
    function loadEnvFields() {
        const envContainer = document.getElementById('env-fields-list');
        envContainer.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> 設定情報を読み込み中...</div>';

        fetch(`${API_BASE}/env`)
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.items) {
                    envContainer.innerHTML = '<p class="text-danger">.env の読み込みに失敗しました。</p>';
                    return;
                }

                envContainer.innerHTML = '';
                data.items.forEach(item => {
                    const row = document.createElement('div');
                    row.className = 'env-row';

                    const inputType = item.is_secret ? 'password' : 'text';

                    row.innerHTML = `
                        <div class="env-key-label">
                            <span class="env-key-badge">${escapeHtml(item.key)}</span>
                        </div>
                        <input type="${inputType}" class="env-value-input" data-key="${escapeHtml(item.key)}" value="${escapeHtml(item.value)}" placeholder="${escapeHtml(item.key)} の値を入力">
                        ${item.is_secret ? `
                            <button type="button" class="btn-icon btn-toggle-secret"><i class="fa-solid fa-eye"></i></button>
                        ` : '<div></div>'}
                    `;
                    envContainer.appendChild(row);
                });

                // Toggle secret visibility
                envContainer.querySelectorAll('.btn-toggle-secret').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const input = btn.previousElementSibling;
                        const icon = btn.querySelector('i');
                        if (input.type === 'password') {
                            input.type = 'text';
                            icon.className = 'fa-solid fa-eye-slash';
                        } else {
                            input.type = 'password';
                            icon.className = 'fa-solid fa-eye';
                        }
                    });
                });
            })
            .catch(() => {
                envContainer.innerHTML = '<p class="text-danger">通信エラーが発生しました。</p>';
            });
    }

    document.getElementById('btn-save-env').addEventListener('click', (e) => {
        e.preventDefault();
        const inputs = document.querySelectorAll('.env-value-input');
        const values = {};
        inputs.forEach(input => {
            const k = input.getAttribute('data-key');
            values[k] = input.value;
        });

        fetch(`${API_BASE}/env`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ values })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                showToast('.env ファイルを保存しました！', 'success');
            } else {
                showToast(data.message || '保存失敗', 'error');
            }
        })
        .catch(() => showToast('通信エラー', 'error'));
    });

    // --- 2. Service Account Upload Logic ---
    function loadServiceAccountStatus() {
        const statusBox = document.getElementById('sa-status-box');
        statusBox.innerHTML = '<div class="loading-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i> 認証情報を確認中...</div>';

        fetch(`${API_BASE}/service-account`)
            .then(res => res.json())
            .then(data => {
                if (!data.exists) {
                    statusBox.innerHTML = `
                        <div class="sa-item">
                            <span class="label">ファイル状態:</span>
                            <span class="value" style="color: var(--danger);"><i class="fa-solid fa-circle-xmark"></i> 未配置 (service_account.json)</span>
                        </div>
                        <p class="field-hint" style="margin-top:0.75rem;">Google スプレッドシートへアクセスするため、右側のアップロードフォームから service_account.json を配置してください。</p>
                    `;
                    return;
                }

                statusBox.innerHTML = `
                    <div class="sa-item">
                        <span class="label">ステータス:</span>
                        <span class="value" style="color: var(--primary);"><i class="fa-solid fa-circle-check"></i> 配置済み</span>
                    </div>
                    <div class="sa-item">
                        <span class="label">サービスアカウント Email:</span>
                        <span class="value">${escapeHtml(data.client_email || '不明')}</span>
                    </div>
                    <div class="sa-item">
                        <span class="label">Project ID:</span>
                        <span class="value">${escapeHtml(data.project_id || '不明')}</span>
                    </div>
                    <div class="sa-item">
                        <span class="label">ファイルサイズ:</span>
                        <span class="value">${(data.size_bytes / 1024).toFixed(2)} KB</span>
                    </div>
                    <div class="sa-item">
                        <span class="label">最終更新日時:</span>
                        <span class="value">${data.updated_at || '不明'}</span>
                    </div>
                `;
            });
    }

    const dropzone = document.getElementById('upload-dropzone');
    const saFileInput = document.getElementById('sa-file-input');
    const selectedFileInfo = document.getElementById('selected-file-info');
    const selectedFileName = document.getElementById('selected-file-name');
    const btnUploadSa = document.getElementById('btn-upload-sa');
    let selectedFile = null;

    if (dropzone) {
        ['dragenter', 'dragover'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropzone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
            });
        });

        dropzone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) handleFileSelection(files[0]);
        });

        saFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) handleFileSelection(e.target.files[0]);
        });
    }

    function handleFileSelection(file) {
        if (!file.name.endsWith('.json')) {
            showToast('JSONファイルを選択してください', 'error');
            return;
        }
        selectedFile = file;
        selectedFileName.textContent = `選択中: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`;
        selectedFileInfo.classList.remove('hidden');
    }

    if (btnUploadSa) {
        btnUploadSa.addEventListener('click', () => {
            if (!selectedFile) return;

            const formData = new FormData();
            formData.append('file', selectedFile);

            fetch(`${API_BASE}/service-account`, {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showToast('service_account.json をアップロードしました！', 'success');
                    selectedFileInfo.classList.add('hidden');
                    selectedFile = null;
                    loadServiceAccountStatus();
                } else {
                    showToast(data.message || 'アップロード失敗', 'error');
                }
            })
            .catch(() => showToast('通信エラーが発生しました', 'error'));
        });
    }

    // --- 3. Periodic Execution (Cron) Logic ---
    const cronEnableToggle = document.getElementById('cron-enable-toggle');
    const cronStatusLabel = document.getElementById('cron-status-label');
    const cronIntervalType = document.getElementById('cron-interval-type');
    const cronValueContainer = document.getElementById('cron-value-container');
    const cronValueLabel = document.getElementById('cron-value-label');
    const cronValueHint = document.getElementById('cron-value-hint');
    const cronIntervalValue = document.getElementById('cron-interval-value');
    const cronTimeInputs = document.getElementById('cron-time-inputs');
    const cronHourGroup = document.getElementById('cron-hour-group');
    const cronMinuteGroup = document.getElementById('cron-minute-group');
    const cronCustomInput = document.getElementById('cron-custom-input');
    const cronHour = document.getElementById('cron-hour');
    const cronMinute = document.getElementById('cron-minute');
    const cronCustomExpr = document.getElementById('cron-custom-expr');
    const cronCmdSnippet = document.getElementById('cron-cmd-snippet');
    const cronWebhookUrl = document.getElementById('cron-webhook-url');

    function loadCronStatus() {
        fetch(`${API_BASE}/schedule`)
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.schedule) return;
                const sch = data.schedule;

                cronEnableToggle.checked = sch.enabled;
                updateCronToggleLabel(sch.enabled);

                cronIntervalType.value = sch.interval_type || 'daily';
                if (cronIntervalValue) cronIntervalValue.value = sch.interval_value || 1;
                cronHour.value = sch.hour !== undefined ? sch.hour : 9;
                cronMinute.value = sch.minute !== undefined ? sch.minute : 0;
                cronCustomExpr.value = sch.custom_cron || '0 9 * * *';

                cronCmdSnippet.textContent = sch.cron_command_snippet || '';
                cronWebhookUrl.textContent = sch.webhook_url || '';

                toggleIntervalFields(sch.interval_type);
            });
    }

    function updateCronToggleLabel(enabled) {
        if (enabled) {
            cronStatusLabel.textContent = '有効 (定期実行稼働中)';
            cronStatusLabel.style.color = 'var(--primary)';
        } else {
            cronStatusLabel.textContent = '無効 (停止中)';
            cronStatusLabel.style.color = 'var(--text-muted)';
        }
    }

    function toggleIntervalFields(type) {
        if (type === 'daily') {
            if (cronValueContainer) cronValueContainer.classList.add('hidden');
            cronTimeInputs.classList.remove('hidden');
            if (cronHourGroup) cronHourGroup.classList.remove('hidden');
            if (cronMinuteGroup) cronMinuteGroup.classList.remove('hidden');
            cronCustomInput.classList.add('hidden');
        } else if (type === 'every_n_hours') {
            if (cronValueContainer) cronValueContainer.classList.remove('hidden');
            if (cronValueLabel) cronValueLabel.textContent = '実行間隔 (N 時間ごと)';
            if (cronValueHint) cronValueHint.textContent = '例: 2 ＝ 2時間ごとに実行 / 4 ＝ 4時間ごとに実行';
            if (cronIntervalValue) cronIntervalValue.setAttribute('max', '23');

            cronTimeInputs.classList.remove('hidden');
            if (cronHourGroup) cronHourGroup.classList.add('hidden');
            if (cronMinuteGroup) cronMinuteGroup.classList.remove('hidden');
            cronCustomInput.classList.add('hidden');
        } else if (type === 'every_n_minutes') {
            if (cronValueContainer) cronValueContainer.classList.remove('hidden');
            if (cronValueLabel) cronValueLabel.textContent = '実行間隔 (N 分ごと)';
            if (cronValueHint) cronValueHint.textContent = '例: 15 ＝ 15分ごとに実行 / 30 ＝ 30分ごとに実行';
            if (cronIntervalValue) cronIntervalValue.setAttribute('max', '59');

            cronTimeInputs.classList.add('hidden');
            cronCustomInput.classList.add('hidden');
        } else if (type === 'custom') {
            if (cronValueContainer) cronValueContainer.classList.add('hidden');
            cronTimeInputs.classList.add('hidden');
            cronCustomInput.classList.remove('hidden');
        } else {
            if (cronValueContainer) cronValueContainer.classList.add('hidden');
            cronTimeInputs.classList.remove('hidden');
            if (cronHourGroup) cronHourGroup.classList.remove('hidden');
            if (cronMinuteGroup) cronMinuteGroup.classList.remove('hidden');
            cronCustomInput.classList.add('hidden');
        }
    }

    if (cronEnableToggle) {
        cronEnableToggle.addEventListener('change', (e) => {
            updateCronToggleLabel(e.target.checked);
        });

        cronIntervalType.addEventListener('change', (e) => {
            toggleIntervalFields(e.target.value);
        });

        document.getElementById('cron-form').addEventListener('submit', (e) => {
            e.preventDefault();

            const payload = {
                enabled: cronEnableToggle.checked,
                interval_type: cronIntervalType.value,
                interval_value: parseInt(cronIntervalValue.value, 10) || 1,
                hour: parseInt(cronHour.value, 10),
                minute: parseInt(cronMinute.value, 10),
                custom_cron: cronCustomExpr.value.trim()
            };

            fetch(`${API_BASE}/schedule`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showToast(data.message, 'success');
                    loadCronStatus();
                } else {
                    showToast(data.message || '保存エラー', 'error');
                }
            })
            .catch(() => showToast('通信エラー', 'error'));
        });
    }

    // --- Initialize App ---
    startPollingMode();
});
