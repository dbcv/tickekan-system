/**
 * Personal Ticket Status Interactive Logic
 */

// 検索絞り込みフィルター
function filterTable() {
    const query = document.getElementById('filter-input').value.toLowerCase().trim();
    const rows = document.querySelectorAll('.ticket-row');
    let visibleCount = 0;

    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        if (text.includes(query)) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });
}

// Ajax データ更新
async function refreshData() {
    const btn = document.getElementById('btn-refresh');
    const icon = document.getElementById('refresh-icon');
    if (icon) icon.classList.add('rotating');
    if (btn) btn.disabled = true;

    try {
        // 現在のURLからAPIパスを生成
        const currentPath = window.location.pathname;
        let apiPath = '';
        if (currentPath.includes('/tickekan-system/status/')) {
            apiPath = currentPath.replace('/tickekan-system/status/', '/tickekan-system/api/status/');
        } else if (currentPath.includes('/status/')) {
            apiPath = currentPath.replace('/status/', '/api/status/');
        }

        if (!apiPath.endsWith('?refresh=1')) {
            apiPath += '?refresh=1';
        }

        const res = await fetch(apiPath);
        const data = await res.json();

        if (data.success && data.status && data.status.valid) {
            // 画面を再読み込みして最新状態を描画
            window.location.reload();
        } else {
            alert('データ更新に失敗しました: ' + (data.message || '不明なエラー'));
        }
    } catch (err) {
        console.error('Refresh error:', err);
        // フォールバックとして通常のブラウザリロード
        window.location.reload();
    } finally {
        if (icon) icon.classList.remove('rotating');
        if (btn) btn.disabled = false;
    }
}
