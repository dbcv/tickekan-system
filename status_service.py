#!/usr/bin/env python3
"""
個人別チケット売上確認ページ用 データ取得・集計・キャッシュサービス
"""

import os
import sys
import time
import json
import fcntl
import threading
from decimal import Decimal
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

from fetch_processed_sheets import fetch_all_processed_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "temp")
CACHE_FILE = os.path.join(CACHE_DIR, "status_cache.json")
LOCK_FILE = os.path.join(CACHE_DIR, "status_cache.lock")

# キャッシュ有効期間（秒）: デフォルト 180秒 (3分)
DEFAULT_CACHE_TTL = int(os.getenv("STATUS_CACHE_TTL", "180"))

_memory_lock = threading.Lock()


def format_number(n: Any) -> Any:
    """数値を整数または見やすい小数形式に変換"""
    try:
        dec = Decimal(str(n))
        if dec == dec.to_integral_value():
            return int(dec)
        return float(dec)
    except Exception:
        return n


class StatusService:
    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL):
        self.cache_ttl = cache_ttl
        os.makedirs(CACHE_DIR, exist_ok=True)

    def _read_cache(self) -> Optional[Dict[str, Any]]:
        """ローカルキャッシュファイルからデータを読み込み"""
        if not os.path.exists(CACHE_FILE):
            return None
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return None

    def _write_cache(self, data: Dict[str, Any]) -> None:
        """ローカルキャッシュファイルにデータを書き込み"""
        try:
            tmp_file = CACHE_FILE + f".tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, CACHE_FILE)
        except Exception as e:
            print(f"[WARNING] キャッシュ書き込み失敗: {e}", file=sys.stderr)

    def get_sheet_data(self, force_refresh: bool = False) -> Tuple[Dict[str, List[Dict[str, Any]]], float]:
        """
        スプレッドシートのデータを取得（キャッシュ有効期間内ならキャッシュを返却）
        :return: ({"Ticket": [...], "Members": [...]}, 取得・更新エポック秒)
        """
        now = time.time()

        # キャッシュが有効かつ強制更新でない場合は即返却
        if not force_refresh:
            cache = self._read_cache()
            if cache and (now - cache.get("timestamp", 0)) < self.cache_ttl:
                return cache.get("data", {}), cache.get("timestamp", now)

        # ファイルロックを用いた安全な更新処理
        with _memory_lock:
            with open(LOCK_FILE, "w") as lock_f:
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX)

                    # ロック取得後に再度キャッシュ有効性を確認
                    if not force_refresh:
                        cache = self._read_cache()
                        if cache and (now - cache.get("timestamp", 0)) < self.cache_ttl:
                            return cache.get("data", {}), cache.get("timestamp", now)

                    # スプレッドシートから最新データを取得
                    print("[INFO] スプレッドシートから最新の Ticket / Members データを取得します...")
                    raw_data = fetch_all_processed_data(as_records=True)

                    cache_payload = {
                        "timestamp": now,
                        "data": raw_data
                    }
                    self._write_cache(cache_payload)
                    return raw_data, now
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)

    def validate_user(self, name: str, user_id: str, members_data: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Members シートの NAME と ID を検証
        """
        if not name or not user_id:
            return False, None

        name_clean = str(name).strip()
        user_id_clean = str(user_id).strip()

        for row in members_data:
            m_name = str(row.get("NAME", "")).strip()
            m_id = str(row.get("ID", "")).strip()

            if m_name == name_clean and m_id == user_id_clean:
                return True, row

        return False, None

    def get_user_status(self, name: str, user_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        指定されたユーザーのチケット予約・売上集計データを取得
        """
        sheet_data, timestamp = self.get_sheet_data(force_refresh=force_refresh)
        members_data = sheet_data.get("Members", [])
        tickets_data = sheet_data.get("Ticket", [])

        is_valid, member_info = self.validate_user(name, user_id, members_data)
        if not is_valid:
            return {
                "valid": False,
                "error": "指定された名前またはIDが正しくありません。URLをご確認ください。",
                "timestamp": timestamp,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
            }

        name_clean = str(name).strip()

        # (種別, 購入者) ごとに集計
        grouped = defaultdict(float)
        stage_totals_raw = defaultdict(float)

        import re

        for row in tickets_data:
            raw_name_str = str(row.get("名前", "")).strip()
            if not raw_name_str:
                continue

            # 半角・全角カンマで人名を分割
            names = [n.strip() for n in re.split(r'[,，]', raw_name_str) if n.strip()]
            if name_clean not in names:
                continue

            stage = str(row.get("種別", "")).strip() or "一般"
            buyer = str(row.get("購入者", "")).strip() or "未記入"
            raw_count = row.get("数", 0)

            try:
                total_row_count = float(raw_count)
            except (ValueError, TypeError):
                total_row_count = 0.0

            # 記載された人数で均等分割（例: 2人なら 1/2）
            num_people = max(len(names), 1)
            count = total_row_count / num_people

            grouped[(stage, buyer)] += count
            stage_totals_raw[stage] += count

        # 一覧リストの作成
        rows = []
        total_count_raw = 0.0

        for (stg, byr), count in grouped.items():
            formatted_count = format_number(count)
            rows.append({
                "stage": stg,
                "buyer": byr,
                "count": formatted_count,
                "count_raw": count
            })
            total_count_raw += count

        # ステージ別小計の整形
        stage_totals = {
            stg: format_number(cnt)
            for stg, cnt in stage_totals_raw.items()
        }

        # 更新日時フォーマット
        last_updated_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

        return {
            "valid": True,
            "name": name_clean,
            "rows": rows,
            "total_count": format_number(total_count_raw),
            "total_count_raw": total_count_raw,
            "reservation_count": len(rows),
            "stage_totals": stage_totals,
            "timestamp": timestamp,
            "last_updated": last_updated_str
        }


# シングルトンインスタンス
status_service = StatusService()
