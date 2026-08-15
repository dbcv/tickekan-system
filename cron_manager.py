import os
import json
import time
import subprocess
import secrets
from typing import Dict, Any, Optional, Tuple

class CronManager:
    """
    レンタルサーバー環境に対応した定期実行 (Cron) 設定・ステータス管理クラス
    """

    CRON_MARKER = "# AUTOTICKET_CRON_JOB"

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.temp_dir = os.path.join(self.workspace_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.config_file = os.path.join(self.workspace_dir, "schedule_config.json")
        self.ensure_config()

    def ensure_config(self):
        """初期設定ファイルの作成"""
        if not os.path.exists(self.config_file):
            default_config = {
                "enabled": False,
                "interval_type": "daily",  # daily, every_n_hours, every_n_minutes, custom
                "hour": 9,
                "minute": 0,
                "interval_value": 1,
                "custom_cron": "0 9 * * *",
                "webhook_token": secrets.token_hex(16),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.save_config(default_config)

    def load_config(self) -> Dict[str, Any]:
        """設定の読み込み"""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "webhook_token" not in data:
                    data["webhook_token"] = secrets.token_hex(16)
                if "interval_value" not in data:
                    data["interval_value"] = 1
                return data
        except Exception:
            return {
                "enabled": False,
                "interval_type": "daily",
                "hour": 9,
                "minute": 0,
                "interval_value": 1,
                "custom_cron": "0 9 * * *",
                "webhook_token": secrets.token_hex(16),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

    def save_config(self, config: Dict[str, Any]):
        """設定の保存"""
        config["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def build_cron_expression(self, interval_type: str, hour: int = 9, minute: int = 0, interval_value: int = 1, custom: str = "0 9 * * *") -> str:
        """スケジュール指定からCron式を生成"""
        val = max(1, int(interval_value or 1))
        if interval_type == "every_n_minutes":
            val = min(59, val)
            return f"*/{val} * * * *"
        elif interval_type == "every_n_hours":
            val = min(23, val)
            return f"{minute} */{val} * * *"
        elif interval_type == "daily":
            return f"{minute} {hour} * * *"
        elif interval_type == "hourly":
            return f"{minute} * * * *"
        elif interval_type == "every_3_hours":
            return f"{minute} */3 * * *"
        elif interval_type == "every_6_hours":
            return f"{minute} */6 * * *"
        elif interval_type == "custom":
            return custom.strip()
        return "0 9 * * *"

    def get_python_command(self) -> str:
        """レンタルサーバー上でのPython実行パスとコマンド"""
        candidates = [
            os.path.join(self.workspace_dir, ".venv", "bin", "python"),
            os.path.join(self.workspace_dir, ".venv", "Scripts", "python.exe"),
            os.path.join(self.workspace_dir, "venv", "bin", "python"),
            os.path.join(self.workspace_dir, "venv", "Scripts", "python.exe"),
        ]
        venv_python = "python3"
        for candidate in candidates:
            if os.path.exists(candidate):
                venv_python = candidate
                break

        log_path = os.path.join(self.temp_dir, "cron_execution.log")
        script_path = os.path.join(self.workspace_dir, "AutoTicket.py")

        return f"cd {self.workspace_dir} && {venv_python} {script_path} >> {log_path} 2>&1"

    def check_system_crontab(self) -> Tuple[bool, Optional[str]]:
        """システムcrontabにAutoTicketが登録されているかチェック"""
        try:
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
            if res.returncode != 0:
                return False, None
            
            lines = res.stdout.splitlines()
            for line in lines:
                if self.CRON_MARKER in line or "AutoTicket.py" in line:
                    return True, line.strip()
            return False, None
        except Exception:
            return False, None

    def update_system_crontab(self, enabled: bool, cron_expr: str) -> bool:
        """システムcrontabの更新（Linux/Unixレンタルサーバー環境）"""
        try:
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
            current_crontab = res.stdout.splitlines() if res.returncode == 0 else []

            # 既存のAutoTicket関連ジョブを除外
            new_crontab = [
                line for line in current_crontab 
                if self.CRON_MARKER not in line and "AutoTicket.py" not in line
            ]

            if enabled:
                cmd = self.get_python_command()
                new_line = f"{cron_expr} {cmd} {self.CRON_MARKER}"
                new_crontab.append(new_line)

            new_crontab_str = "\n".join(new_crontab) + "\n"
            
            proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=new_crontab_str)
            return proc.returncode == 0
        except Exception:
            return False

    def get_status(self, request_host: str = "") -> Dict[str, Any]:
        """現在の定期実行設定ステータスと情報"""
        config = self.load_config()
        system_enabled, active_line = self.check_system_crontab()

        cron_expr = self.build_cron_expression(
            config.get("interval_type", "daily"),
            config.get("hour", 9),
            config.get("minute", 0),
            config.get("interval_value", 1),
            config.get("custom_cron", "0 9 * * *")
        )

        python_cmd = self.get_python_command()
        cron_command_snippet = f"{cron_expr} {python_cmd}"

        host = request_host or "localhost:5000"
        scheme = "https" if "gekidanshirochan.com" in host else "http"
        webhook_url = f"{scheme}://{host}/tickekan-system/api/cron/run?token={config.get('webhook_token')}"

        return {
            "enabled": config.get("enabled", False),
            "system_crontab_active": system_enabled,
            "active_crontab_line": active_line,
            "interval_type": config.get("interval_type", "daily"),
            "hour": config.get("hour", 9),
            "minute": config.get("minute", 0),
            "interval_value": config.get("interval_value", 1),
            "custom_cron": config.get("custom_cron", "0 9 * * *"),
            "cron_expression": cron_expr,
            "cron_command_snippet": cron_command_snippet,
            "webhook_url": webhook_url,
            "webhook_token": config.get("webhook_token"),
            "updated_at": config.get("updated_at"),
        }

    def set_schedule(self, enabled: bool, interval_type: str, hour: int = 9, minute: int = 0, interval_value: int = 1, custom_cron: str = "0 9 * * *") -> Dict[str, Any]:
        """スケジュール設定の更新"""
        config = self.load_config()
        config["enabled"] = enabled
        config["interval_type"] = interval_type
        config["hour"] = int(hour)
        config["minute"] = int(minute)
        config["interval_value"] = int(interval_value)
        config["custom_cron"] = custom_cron

        self.save_config(config)

        cron_expr = self.build_cron_expression(interval_type, hour, minute, interval_value, custom_cron)
        
        # Linux / Unix環境でcrontabが利用可能な場合は自動適用を試みる
        crontab_success = self.update_system_crontab(enabled, cron_expr)

        return self.get_status()

# グローバルマネージャーのインスタンス
workspace_dir = os.path.dirname(os.path.abspath(__file__))
cron_manager = CronManager(workspace_dir)
