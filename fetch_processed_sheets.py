#!/usr/bin/env python3
"""
送信先スプレッドシートから加工済みデータ (Ticket / Members) を取得する独立スクリプト (プロトタイプ)
"""

import os
import sys
import json
import warnings
from typing import List, Dict, Any, Optional

# google-auth の FutureWarning 警告の抑制
warnings.filterwarnings("ignore", category=FutureWarning)

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# プロジェクトルートのパスを基準に設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", os.path.join(BASE_DIR, "service_account.json"))

# Google Sheets API / Drive API スコープ定義
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 取得対象のワークシート gid 定義 (環境変数から取得、未設定時はデフォルト値)
TICKET_GID = int(os.getenv("SPREADSHEET_TICKET_GID", "934641883"))
MEMBERS_GID = int(os.getenv("SPREADSHEET_MEMBERS_GID", "708315325"))

TARGET_SHEETS = {
    "Ticket": TICKET_GID,
    "Members": MEMBERS_GID,
}


def get_gspread_client() -> gspread.Client:
    """Google Sheets API クライアント認証・取得"""
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return gspread.authorize(creds)

    service_json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_json_str:
        info = json.loads(service_json_str)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    client_secret_file = os.getenv("GOOGLE_CLIENT_SECRET_FILE", os.path.join(BASE_DIR, "client_secret.json"))
    if os.path.exists(client_secret_file):
        return gspread.oauth(
            credentials_filename=client_secret_file,
            authorized_user_filename=os.path.join(BASE_DIR, "authorized_user.json"),
        )

    raise FileNotFoundError("Google スプレッドシート API の認証情報が見つかりません。")


def get_worksheet_by_gid(spreadsheet: gspread.Spreadsheet, gid: int) -> Optional[gspread.Worksheet]:
    """gidからワークシートを取得（互換性のためにget_worksheet_by_idまたはループフォールバック）"""
    try:
        # gspread 3.7.0+
        ws = spreadsheet.get_worksheet_by_id(gid)
        if ws:
            return ws
    except Exception:
        pass

    # フォールバック: 全ワークシートを探索
    for ws in spreadsheet.worksheets():
        if ws.id == gid or str(ws.id) == str(gid):
            return ws
    return None


def fetch_sheet_data(
    spreadsheet: gspread.Spreadsheet,
    sheet_name: str,
    gid: int,
    as_records: bool = False
) -> List[Any]:
    """
    指定されたgidのワークシートからデータを取得
    :param spreadsheet: Spreadsheetオブジェクト
    :param sheet_name: シートの論理名（表示用）
    :param gid: シートのgid
    :param as_records: Trueの場合はヘッダー付き辞書リスト、Falseの場合は2次元配列(リストのリスト)
    :return: 取得したデータ
    """
    print(f"[INFO] '{sheet_name}' (gid={gid}) のデータを取得中...")
    worksheet = get_worksheet_by_gid(spreadsheet, gid)
    
    if not worksheet:
        raise ValueError(f"gid={gid} のワークシートが見つかりませんでした。")

    print(f"[INFO] ワークシートが見つかりました: タイトル='{worksheet.title}'")
    
    if as_records:
        # 1行目をキーとした辞書リストとして取得（空行や計算式も取得）
        data = worksheet.get_all_records()
    else:
        # 2次元リスト (行×列) として全セルを取得
        data = worksheet.get_all_values()

    print(f"[SUCCESS] '{worksheet.title}' から {len(data)} 件のデータを取得しました。")
    return data


def fetch_all_processed_data(as_records: bool = False) -> Dict[str, List[Any]]:
    """
    Ticket と Members の両方のデータを取得して辞書形式で返します。
    """
    if not SPREADSHEET_URL:
        raise ValueError(".env に SPREADSHEET_URL が設定されていません。")

    gc = get_gspread_client()
    spreadsheet = gc.open_by_url(SPREADSHEET_URL)
    print(f"[INFO] スプレッドシートを開きました: {spreadsheet.title}")

    results = {}
    for name, gid in TARGET_SHEETS.items():
        try:
            results[name] = fetch_sheet_data(spreadsheet, name, gid, as_records=as_records)
        except Exception as e:
            print(f"[ERROR] '{name}' (gid={gid}) の取得に失敗しました: {e}", file=sys.stderr)
            results[name] = []

    return results


def main():
    print("=" * 60)
    print(" スプレッドシート データ取得プログラム (Ticket / Members)")
    print("=" * 60)

    try:
        data = fetch_all_processed_data(as_records=False)

        for name, rows in data.items():
            print("\n" + "-" * 40)
            print(f"【{name} データサマリー】")
            print(f"総行数: {len(rows)}")
            if rows:
                print(f"ヘッダー (1行目): {rows[0]}")
                if len(rows) > 1:
                    print(f"データ先頭行 (2行目): {rows[1]}")
            print("-" * 40)

        print("\n[SUCCESS] すべてのデータ取得が完了しました。")

    except Exception as e:
        print(f"\n[ERROR] エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
