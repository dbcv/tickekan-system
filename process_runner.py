import os
import sys
import time
import signal
import json
import threading
import subprocess
import queue
from typing import List, Dict, Any, Optional

class ProcessRunner:
    """
    AutoTicket の実行プロセス管理・ログ収集・標準入力 (R7 URL入力等) 制御クラス
    CGI / WSGI / レンタルサーバー環境（プロセス非永続的環境）に完全対応したファイルベース永続化実装
    """
    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.temp_dir = os.path.join(self.workspace_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.log_file = os.path.join(self.temp_dir, "execution.log")
        self.pid_file = os.path.join(self.temp_dir, "execution.pid")
        self.status_file = os.path.join(self.temp_dir, "execution_status.json")
        self.fifo_file = os.path.join(self.temp_dir, "execution.fifo")
        self.lock = threading.Lock()
        self.listeners: List[queue.Queue] = []

    def _is_pid_running(self, pid: int) -> bool:
        """指定されたPIDのプロセスが生存しているか判定"""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError, PermissionError):
            return False

    def _read_status_file(self) -> Dict[str, Any]:
        """status_file からJSONデータを読み込み"""
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "is_running": False,
            "is_waiting_input": False,
            "input_prompt": "",
            "last_run_time": None,
            "last_run_status": "未実行",
            "last_exit_code": None,
            "current_job_name": "",
        }

    def _write_status_file(self, data: Dict[str, Any]):
        """status_file にJSONデータを保存"""
        try:
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """現在のプロセスの実行状態を取得 (ファイルベース同期)"""
        with self.lock:
            status = self._read_status_file()

            # PIDファイルの確認とプロセス生存確認
            pid = None
            if os.path.exists(self.pid_file):
                try:
                    with open(self.pid_file, "r") as f:
                        pid = int(f.read().strip())
                except Exception:
                    pid = None

            is_active = self._is_pid_running(pid) if pid else False

            if is_active:
                status["is_running"] = True
                # ログ末尾から入力待ちを検出
                if os.path.exists(self.log_file):
                    try:
                        with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                            lines = f.readlines()[-10:]  # 末尾10行
                            for line in reversed(lines):
                                if "[INPUT REQUIRED]" in line or "メール内のログインURLを貼り付けてEnter" in line:
                                    status["is_waiting_input"] = True
                                    status["input_prompt"] = line.strip()
                                    status["last_run_status"] = "入力待ち"
                                    break
                            else:
                                if status.get("is_waiting_input"):
                                    status["is_waiting_input"] = False
                                    status["input_prompt"] = ""
                                    status["last_run_status"] = "実行中"
                    except Exception:
                        pass
            else:
                # プロセスが終了しているがファイルが is_running: True の場合の補正
                if status.get("is_running"):
                    status["is_running"] = False
                    status["is_waiting_input"] = False
                    status["input_prompt"] = ""
                    # ログの最終状態から完了/エラーを判定
                    log_text = ""
                    if os.path.exists(self.log_file):
                        try:
                            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                                log_text = f.read()
                        except Exception:
                            pass
                    if "[ERROR]" in log_text or "[FATAL]" in log_text or "Traceback" in log_text:
                        status["last_run_status"] = "エラー"
                    elif "[SUCCESS]" in log_text or "正常終了" in log_text or "完了" in log_text:
                        status["last_run_status"] = "完了"
                    else:
                        status["last_run_status"] = "完了"
                    self._write_status_file(status)

                # クリーンアップ
                if os.path.exists(self.pid_file):
                    try:
                        os.remove(self.pid_file)
                    except Exception:
                        pass

            log_count = 0
            if os.path.exists(self.log_file):
                try:
                    with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                        log_count = len(f.readlines())
                except Exception:
                    pass

            status["log_count"] = log_count
            return status

    def append_log_line(self, text: str, log_type: str = "stdout"):
        """ログファイルに1行追記"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {text}\n"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception:
            pass

    def get_logs_after(self, after_id: int = 0) -> List[Dict[str, Any]]:
        """指定されたログID (行番号) 以降の新着ログを取得"""
        if not os.path.exists(self.log_file):
            return []

        results = []
        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for idx, line in enumerate(lines, start=1):
                    if idx > after_id:
                        line_str = line.rstrip("\r\n")
                        timestamp = time.strftime("%H:%M:%S")
                        text = line_str
                        log_type = "stdout"

                        # [YYYY-MM-DD HH:MM:SS] プレフィックス解析
                        if line_str.startswith("[") and "]" in line_str:
                            parts = line_str.split("]", 1)
                            ts_part = parts[0].lstrip("[")
                            if " " in ts_part:
                                timestamp = ts_part.split(" ")[1]
                            else:
                                timestamp = ts_part
                            text = parts[1].lstrip()

                        if "[SYSTEM]" in text or "[START]" in text or "[SUCCESS]" in text:
                            log_type = "system"
                        elif "[ERROR]" in text or "[FATAL]" in text or "Traceback" in text:
                            log_type = "stderr"
                        elif "[USER INPUT]" in text:
                            log_type = "input"

                        results.append({
                            "id": idx,
                            "timestamp": timestamp,
                            "text": text,
                            "type": log_type
                        })
        except Exception:
            pass
        return results

    def clear_logs(self):
        """ログファイルのクリア"""
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                f.truncate(0)
        except Exception:
            pass

    def run_script(self, script_name: str = "AutoTicket.py", args: Optional[List[str]] = None) -> bool:
        """
        指定されたスクリプトを独立したバックグラウンドプロセスとして実行
        """
        status = self.get_status()
        if status["is_running"]:
            return False

        # ログファイルを初期化
        self.clear_logs()

        # 実行用のPythonインタープリタパス決定 (.venv -> venv -> sys.executable)
        candidates = [
            os.path.join(self.workspace_dir, ".venv", "bin", "python"),
            os.path.join(self.workspace_dir, ".venv", "Scripts", "python.exe"),
            os.path.join(self.workspace_dir, "venv", "bin", "python"),
            os.path.join(self.workspace_dir, "venv", "Scripts", "python.exe"),
        ]
        python_bin = sys.executable
        for candidate in candidates:
            if os.path.exists(candidate):
                python_bin = candidate
                break

        script_path = os.path.join(self.workspace_dir, script_name)
        
        # stdbuf -oL -eL によりstdout/stderrの行バッファリングを強制的適用（リアルタイムログ出力）
        cmd = ["stdbuf", "-oL", "-eL", python_bin, "-u", script_path]
        if args:
            cmd.extend(args)

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # FIFO（名前付きパイプ）の準備 (標準入力渡し用)
        if os.path.exists(self.fifo_file):
            try:
                os.remove(self.fifo_file)
            except Exception:
                pass

        try:
            os.mkfifo(self.fifo_file)
        except Exception:
            pass

        # 開始ログの書き込み
        self.append_log_line("============================================================", "system")
        self.append_log_line(f"[START] {script_name} の実行を開始します...", "system")
        self.append_log_line("============================================================", "system")

        # リダイレクト用ファイル記述子 (buffering=1 で行単位即時書き込み)
        log_fd = open(self.log_file, "a", encoding="utf-8", buffering=1)
        
        # FIFOを開く (ノンブロッキング/r+モード)
        fifo_fd = None
        if os.path.exists(self.fifo_file):
            try:
                fifo_fd = open(self.fifo_file, "r+")
            except Exception:
                fifo_fd = subprocess.PIPE
        else:
            fifo_fd = subprocess.PIPE

        try:
            # CGIプロセスグループから切り離して独立プロセスを起動 (start_new_session=True)
            proc = subprocess.Popen(
                cmd,
                cwd=self.workspace_dir,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                stdin=fifo_fd,
                env=env,
                start_new_session=True
            )

            # PIDとステータスの保存
            with open(self.pid_file, "w") as f:
                f.write(str(proc.pid))

            new_status = {
                "is_running": True,
                "is_waiting_input": False,
                "input_prompt": "",
                "last_run_time": time.time(),
                "last_run_status": "実行中",
                "last_exit_code": None,
                "current_job_name": script_name,
            }
            self._write_status_file(new_status)
            return True
        except Exception as e:
            self.append_log_line(f"[FATAL] プロセス起動例外: {e}", "stderr")
            new_status = {
                "is_running": False,
                "is_waiting_input": False,
                "input_prompt": "",
                "last_run_time": time.time(),
                "last_run_status": "エラー",
                "last_exit_code": -1,
                "current_job_name": script_name,
            }
            self._write_status_file(new_status)
            return False

    def send_input(self, text: str) -> bool:
        """対話入力を FIFO パイプへ送信"""
        status = self.get_status()
        if not status["is_running"]:
            return False

        display_text = text if len(text) <= 100 else text[:95] + "..."
        self.append_log_line(f"[USER INPUT] > {display_text}", "input")

        success = False
        if os.path.exists(self.fifo_file):
            try:
                with open(self.fifo_file, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
                    f.flush()
                success = True
            except Exception as e:
                self.append_log_line(f"[ERROR] FIFO書き込み失敗: {e}", "stderr")

        if success:
            status["is_waiting_input"] = False
            status["input_prompt"] = ""
            status["last_run_status"] = "実行中"
            self._write_status_file(status)

        return success

    def stop_process(self) -> bool:
        """プロセスの強制停止"""
        status = self.get_status()
        if not status["is_running"]:
            return False

        pid = None
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, "r") as f:
                    pid = int(f.read().strip())
            except Exception:
                pass

        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass

        if os.path.exists(self.pid_file):
            try:
                os.remove(self.pid_file)
            except Exception:
                pass

        self.append_log_line("[SYSTEM] ユーザー要求によりプロセス強制停止シグナルを送信しました。", "system")

        status["is_running"] = False
        status["is_waiting_input"] = False
        status["input_prompt"] = ""
        status["last_run_status"] = "強制停止"
        status["last_exit_code"] = -1
        self._write_status_file(status)
        return True

# グローバルランナーのインスタンス生成
workspace_dir = os.path.dirname(os.path.abspath(__file__))
runner = ProcessRunner(workspace_dir)
