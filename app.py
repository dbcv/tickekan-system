import os
import json
import time
import json
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename

from process_runner import runner, workspace_dir
from cron_manager import cron_manager

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "autoticket-secret-key-2026"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB max upload

ENV_FILE = os.path.join(workspace_dir, ".env")
ENV_EXAMPLE_FILE = os.path.join(workspace_dir, ".env.example")
SERVICE_ACCOUNT_FILE = os.path.join(workspace_dir, "service_account.json")


def parse_env_file() -> list:
    """
    .env (および .env.example) からキーの一覧と値を取得する
    """
    keys_order = []
    env_values = {}

    # まず .env.example があればキーの順序テンプレートとして読み込み
    if os.path.exists(ENV_EXAMPLE_FILE):
        with open(ENV_EXAMPLE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _ = line.split("=", 1)
                    k = k.strip()
                    if k not in keys_order:
                        keys_order.append(k)

    # 実際の .env ファイルを読み込み
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k not in keys_order:
                        keys_order.append(k)
                    env_values[k] = v

    result = []
    for k in keys_order:
        result.append({
            "key": k,
            "value": env_values.get(k, ""),
            "is_secret": ("PASSWORD" in k or "SECRET" in k or "KEY" in k)
        })

    return result


def save_env_file(new_values: dict) -> bool:
    """
    .env ファイルのコメント等を保持しつつ値を更新・保存する
    """
    lines = []
    existing_keys = set()

    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    k = k.strip()
                    if k in new_values:
                        lines.append(f"{k}={new_values[k]}\n")
                        existing_keys.add(k)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    # 新規キーがあれば末尾に追加
    for k, v in new_values.items():
        if k not in existing_keys:
            lines.append(f"{k}={v}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return True


def multi_route(rule, **options):
    """
    /api/... および /tickekan-system/api/... の両方のプレフィックスにルートを登録するデコレータ
    """
    def decorator(f):
        endpoint = options.pop("endpoint", None)
        rules = [rule]
        if rule.startswith("/api"):
            rules.append("/tickekan-system" + rule)
        elif rule == "/":
            rules.append("/tickekan-system")
            rules.append("/tickekan-system/")

        for idx, r in enumerate(rules):
            ep = (endpoint or f.__name__) if idx == 0 else f"{endpoint or f.__name__}_{idx}"
            app.add_url_rule(r, ep, f, **options)
        return f
    return decorator


@app.route("/tickekan-system/static/<path:filename>")
def serve_tickekan_static(filename):
    return send_from_directory(app.static_folder, filename)


@multi_route("/")
def index():
    """メインダッシュボード画面"""
    return render_template("index.html")


# ==========================================
# 1. .env エディタ API
# ==========================================
@multi_route("/api/env", methods=["GET"])
def get_env():
    """.env の設定項目と値を取得"""
    items = parse_env_file()
    return jsonify({"success": True, "items": items})


@multi_route("/api/env", methods=["POST"])
def update_env():
    """.env の値を更新保存"""
    data = request.json or {}
    values = data.get("values", {})
    if not isinstance(values, dict):
        return jsonify({"success": False, "message": "無効なデータ形式です"}), 400

    try:
        save_env_file(values)
        return jsonify({"success": True, "message": ".env ファイルを保存しました！"})
    except Exception as e:
        return jsonify({"success": False, "message": f"保存エラー: {e}"}), 500


# ==========================================
# 2. service_account.json アップロード & ステータス API
# ==========================================
@multi_route("/api/service-account", methods=["GET"])
def get_service_account_status():
    """service_account.json の存在状態および内容情報を取得"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return jsonify({
            "exists": False,
            "message": "service_account.json が配置されていません"
        })

    try:
        with open(SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        stat = os.stat(SERVICE_ACCOUNT_FILE)
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))

        return jsonify({
            "exists": True,
            "type": data.get("type", "service_account"),
            "project_id": data.get("project_id", "不明"),
            "client_email": data.get("client_email", "不明"),
            "client_id": data.get("client_id", "不明"),
            "size_bytes": stat.st_size,
            "updated_at": updated_at
        })
    except Exception as e:
        return jsonify({
            "exists": True,
            "valid": False,
            "error": f"JSON解析エラー: {e}"
        })


@multi_route("/api/service-account", methods=["POST"])
def upload_service_account():
    """service_account.json のアップロード"""
    if "file" not in request.files:
        return jsonify({"success": False, "message": "ファイルが添付されていません"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "ファイルが選択されていません"}), 400

    try:
        content = file.read().decode("utf-8")
        json_data = json.loads(content)

        # 最低限のバリデーション
        if "type" not in json_data or json_data.get("type") != "service_account":
            return jsonify({
                "success": False,
                "message": "有効な Google サービスアカウント JSON ファイルではありません（type: service_account が必要です）"
            }), 400

        # ファイルへ書き込み
        with open(SERVICE_ACCOUNT_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        return jsonify({
            "success": True,
            "message": "service_account.json を正常にアップロード・保存しました！",
            "client_email": json_data.get("client_email"),
            "project_id": json_data.get("project_id")
        })
    except json.JSONDecodeError:
        return jsonify({"success": False, "message": "アップロードされたファイルが正しいJSON形式ではありません"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"アップロード処理エラー: {e}"}), 500


# ==========================================
# 3. 定期実行 (Cron) 管理 API
# ==========================================
@multi_route("/api/schedule", methods=["GET"])
def get_schedule():
    """定期実行の設定状態を取得"""
    status = cron_manager.get_status(request.host)
    return jsonify({"success": True, "schedule": status})


@multi_route("/api/schedule", methods=["POST"])
def update_schedule():
    """定期実行の設定更新・開始・停止"""
    data = request.json or {}
    enabled = bool(data.get("enabled", False))
    interval_type = data.get("interval_type", "daily")
    hour = int(data.get("hour", 9))
    minute = int(data.get("minute", 0))
    interval_value = int(data.get("interval_value", 1))
    custom_cron = data.get("custom_cron", "0 9 * * *")

    new_status = cron_manager.set_schedule(enabled, interval_type, hour, minute, interval_value, custom_cron)
    return jsonify({
        "success": True,
        "message": "定期実行スケジュールを更新しました！" if enabled else "定期実行を停止しました。",
        "schedule": new_status
    })


@multi_route("/api/cron/run", methods=["GET", "POST"])
def trigger_cron_web():
    """外部Web Cron / レンタルサーバーCron用のWebフックエンドポイント"""
    token = request.args.get("token") or request.headers.get("X-Cron-Token")
    config = cron_manager.load_config()

    if not token or token != config.get("webhook_token"):
        return jsonify({"success": False, "message": "認証トークンが無効です"}), 403

    # 手動実行でAutoTicketを開始
    started = runner.run_script("AutoTicket.py", args=["--cron"])
    if started:
        return jsonify({"success": True, "message": "AutoTicket の定期トリガー実行を開始しました"})
    else:
        return jsonify({"success": False, "message": "すでに別のAutoTicketプロセスが実行中です"}), 409


# ==========================================
# 4. AutoTicket 実行 & リアルタイムログ API
# ==========================================
@multi_route("/api/execution/run", methods=["POST"])
def run_autoticket():
    """AutoTicket の手動実行開始"""
    started = runner.run_script("AutoTicket.py")
    if started:
        return jsonify({"success": True, "message": "AutoTicket の実行を開始しました！"})
    else:
        return jsonify({"success": False, "message": "すでにプロセスが実行中です"}), 409


@multi_route("/api/execution/stop", methods=["POST"])
def stop_autoticket():
    """AutoTicket の手動強制停止"""
    stopped = runner.stop_process()
    if stopped:
        return jsonify({"success": True, "message": "プロセスに停止要求を送信しました"})
    else:
        return jsonify({"success": False, "message": "実行中のプロセスがありません"}), 400


@multi_route("/api/execution/input", methods=["POST"])
def send_process_input():
    """R7 ログインURL等の対話入力を標準入力へ送信"""
    data = request.json or {}
    user_input = data.get("input", "").strip()

    if not user_input:
        return jsonify({"success": False, "message": "入力内容が空です"}), 400

    sent = runner.send_input(user_input)
    if sent:
        return jsonify({"success": True, "message": "標準入力へ正常に送信しました！"})
    else:
        return jsonify({"success": False, "message": "現在入力待ちのプロセスがありません"}), 400


@multi_route("/api/execution/clear", methods=["POST"])
def clear_logs():
    """ログバッファの消去"""
    runner.clear_logs()
    return jsonify({"success": True, "message": "ログをクリアしました"})


@multi_route("/api/execution/status", methods=["GET"])
def get_execution_status():
    """実行ステータスのみを返却（ログテキスト不含）"""
    status = runner.get_status()
    return jsonify({
        "success": True,
        "status": status
    })


@multi_route("/api/execution/logs/poll")
def poll_logs():

    """ポーリング形式でのログ取得 (WSGI・スレッド制限環境でのロック回避用)"""
    after_id = int(request.args.get("after_id", 0))
    logs = runner.get_logs_after(after_id)
    status = runner.get_status()
    return jsonify({
        "success": True,
        "status": status,
        "logs": logs
    })


@multi_route("/api/execution/logs/stream")
def stream_logs():
    """Server-Sent Events (SSE) でリアルタイムログ配信 (最大30秒で一旦セッションをリセットしスレッドを解放)"""
    def generate():
        q = runner.subscribe()
        start_time = time.time()
        try:
            # 接続時に現在のステータスと既存の過去ログ全件を送信
            initial_payload = {
                "event": "init",
                "status": runner.get_status(),
                "logs": runner.logs
            }
            yield f"data: {json.dumps(initial_payload, ensure_ascii=False)}\n\n"

            while True:
                # 30秒経過したらスレッド解放のためループを出る (ブラウザEventSourceが自動再接続)
                if time.time() - start_time > 30:
                    yield f"data: {json.dumps({'event': 'reconnect'})}\n\n"
                    break

                try:
                    msg = q.get(timeout=5)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except Exception:
                    # ハートビート
                    ping_payload = {"event": "ping", "time": time.time()}
                    yield f"data: {json.dumps(ping_payload)}\n\n"
        finally:
            runner.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
