"""
画像生成バックグラウンドタスクおよびアセット管理マネージャー
CGI / レンタルサーバー環境（プロセス非永続的環境）に完全対応したファイルベース永続化実装
"""

import os
import sys
import time
import json
import subprocess
from typing import Dict, Any, Optional

from generate_personal_images import (
    BASE_DIR,
    get_available_fonts,
    resolve_font_path
)


class ImageGenerationManager:
    def __init__(self):
        self.workspace_dir = BASE_DIR
        self.temp_dir = os.path.join(self.workspace_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        self.status_file = os.path.join(self.temp_dir, "image_gen_status.json")
        self.pid_file = os.path.join(self.temp_dir, "image_gen.pid")
        self.config_file = os.path.join(self.temp_dir, "image_gen_config.json")

    def _is_pid_running(self, pid: int) -> bool:
        """指定されたPIDのプロセスが生存しているか判定"""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError, PermissionError):
            return False

    def _get_saved_font_path(self) -> Optional[str]:
        """設定ファイルから選択中フォントパスを取得"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    p = data.get("selected_font_path")
                    if p and os.path.exists(p):
                        return p
            except Exception:
                pass
        
        fonts = get_available_fonts()
        return fonts[0]["path"] if fonts else None

    def _save_font_path(self, font_path: str):
        """選択中フォントパスを設定ファイルに保存"""
        try:
            data = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["selected_font_path"] = font_path
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_config(self) -> Dict[str, Any]:
        """設定・アセット状態および直前の生成結果を取得"""
        image_dir = os.path.join(self.workspace_dir, "media", "image")
        os.makedirs(image_dir, exist_ok=True)

        bg_status = {}
        for bg_type in ["bg-top", "bg-loop", "bg-bottom"]:
            fname = f"{bg_type}.png"
            fpath = os.path.join(image_dir, fname)
            exists = os.path.exists(fpath)
            bg_status[bg_type] = {
                "exists": exists,
                "filename": fname,
                "url": f"/tickekan-system/api/images/background/preview/{fname}?t={int(os.path.getmtime(fpath))}" if exists else None
            }

        fonts = get_available_fonts()
        selected_font = self._get_saved_font_path()

        zip_path = os.path.join(self.workspace_dir, "personal_images.zip")
        zip_exists = os.path.exists(zip_path)
        zip_size = os.path.getsize(zip_path) if zip_exists else 0
        zip_mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(zip_path))) if zip_exists else None

        return {
            "backgrounds": bg_status,
            "fonts": fonts,
            "selected_font": selected_font,
            "zip_info": {
                "exists": zip_exists,
                "size_bytes": zip_size,
                "updated_at": zip_mtime
            },
            "status": self.get_status()
        }

    def set_font(self, font_path: str) -> bool:
        """使用フォントを設定・永続化"""
        if os.path.exists(font_path):
            self._save_font_path(font_path)
            return True
        return False

    def delete_font(self, font_path: str) -> bool:
        """アップロードされたフォントファイルを削除（解除）"""
        fonts_dir = os.path.abspath(os.path.join(self.workspace_dir, "fonts"))
        target_path = os.path.abspath(font_path)

        if not target_path.startswith(fonts_dir):
            return False

        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                return False

        current_selected = self._get_saved_font_path()
        if current_selected == font_path:
            remaining_fonts = get_available_fonts()
            new_font = remaining_fonts[0]["path"] if remaining_fonts else ""
            self._save_font_path(new_font)

        return True

    def get_status(self) -> Dict[str, Any]:
        """現在の画像生成タスクの進行状態を取得 (CGIプロセス非依存)"""
        # 1. PIDの確認
        pid = None
        if os.path.exists(self.pid_file):
            try:
                with open(self.pid_file, "r") as f:
                    pid = int(f.read().strip())
            except Exception:
                pid = None

        is_running = self._is_pid_running(pid) if pid else False

        # 2. 進捗ファイルの読み込み
        status_data = {
            "is_generating": False,
            "status": "idle",
            "message": "待機中",
            "progress_current": 0,
            "progress_total": 0,
            "progress_percent": 0,
            "error_message": None,
            "last_result": None
        }

        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    status_data = json.load(f)
            except Exception:
                pass

        if is_running:
            status_data["is_generating"] = True
            if status_data.get("status") != "running":
                status_data["status"] = "running"
        else:
            # プロセスが終了している場合
            if status_data.get("is_generating"):
                status_data["is_generating"] = False
                if status_data.get("status") == "running":
                    status_data["status"] = "success"

            # PIDファイルのクリーンアップ
            if os.path.exists(self.pid_file):
                try:
                    os.remove(self.pid_file)
                except Exception:
                    pass

        return status_data

    def start_generation(self) -> bool:
        """バックグラウンドプロセスとして画像生成を非同期起動 (CGI終了後も持続)"""
        current_status = self.get_status()
        if current_status.get("is_generating"):
            return False

        # 初期ステータスを書き出し
        init_data = {
            "is_generating": True,
            "status": "running",
            "message": "画像生成プロセスを起動しています...",
            "progress_current": 0,
            "progress_total": 0,
            "progress_percent": 0,
            "error_message": None,
            "last_result": None
        }
        with open(self.status_file, "w", encoding="utf-8") as f:
            json.dump(init_data, f, indent=2, ensure_ascii=False)

        # 実行コマンド構築
        python_bin = sys.executable
        script_path = os.path.join(self.workspace_dir, "generate_personal_images.py")
        selected_font = self._get_saved_font_path() or ""

        cmd = [
            python_bin,
            script_path,
            "--progress-file", self.status_file
        ]
        if selected_font:
            cmd.extend(["--font", selected_font])

        # OSバックグラウンドプロセスとして起動 (start_new_session=True により親プロセス終了後も継続)
        log_out_path = os.path.join(self.temp_dir, "image_gen.log")
        log_out = open(log_out_path, "a", encoding="utf-8")

        proc = subprocess.Popen(
            cmd,
            cwd=self.workspace_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )

        with open(self.pid_file, "w") as f:
            f.write(str(proc.pid))

        return True


image_manager = ImageGenerationManager()
