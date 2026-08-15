# Teket_login.pyおよびr7_login.pyを使用して、teketおよびR7のCSVをダウンロードし、Googleスプレッドシートに書きこむプログラム

import os
import csv
import sys
import warnings
from typing import List, Optional, Any
import json

# google-auth の FutureWarning 警告の抑制
warnings.filterwarnings("ignore", category=FutureWarning)

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

from teket_login import TeketClient
from r7_login import R7Client


# .env から環境変数を読み込み
load_dotenv()

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

# Google Sheets API / Drive API スコープ定義
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def parse_cell_value(val: Any) -> Any:
    """セルを適切なデータ型（int / float / str）に数値変換"""
    if not isinstance(val, str):
        return val

    s = val.strip()
    if not s:
        return ""

    # 電話番号や郵便番号、先頭が'0'で始まる複数の数字 (例: "09012345678", "00123") は文字列のまま保持
    if len(s) > 1 and s.startswith("0") and s.isdigit():
        return s

    # 3桁カンマ区切りの数値文字列（例: "1,000"）に対応
    s_no_comma = s.replace(",", "")

    # 整数への変換
    try:
        return int(s_no_comma)
    except ValueError:
        pass

    # 小数への変換
    try:
        return float(s_no_comma)
    except ValueError:
        pass

    return val


def read_csv_rows(filepath: str) -> List[List[Any]]:
    """CSVファイルをエンコーディング（utf-8-sig / cp932 / utf-8）で読み込み、セルを数値変換"""
    encodings = ["utf-8-sig", "cp932", "utf-8", "shift_jis"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                reader = csv.reader(f)
                raw_rows = list(reader)

                parsed_rows = []
                for row_idx, row in enumerate(raw_rows):
                    # 1行目(ヘッダー)はそのまま文字列
                    if row_idx == 0:
                        parsed_rows.append(row)
                    else:
                        parsed_rows.append([parse_cell_value(cell) for cell in row])

                print(f"[INFO] '{filepath}' エンコーディング '{enc}' で読み込みました ({len(parsed_rows)} 行)。")
                return parsed_rows
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError(f"CSVファイル '{filepath}' の文字コード判別に失敗しました。")


def get_gspread_client() -> gspread.Client:
    """
    Google Sheets API クライアント認証・取得。
    1. service_account.json (サービスアカウント鍵ファイル)
    2. .env の GOOGLE_SERVICE_ACCOUNT_JSON (JSON文字列)
    3. client_secret.json (OAuth 2.0 ユーザーログインブラウザ認証)
    の優先順で認証を試みます。
    """
    # 1. サービスアカウント JSON ファイルが存在する場合
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return gspread.authorize(creds)

    # 2. 環境変数にサービスアカウント JSON が直接定義されている場合
    service_json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if service_json_str:
        info = json.loads(service_json_str)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    # 3. OAuth Client Secret が存在する場合（ブラウザでのユーザー認証）
    client_secret_file = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json")
    if os.path.exists(client_secret_file):
        print("[INFO] OAuth 2.0 ユーザー認証 (client_secret.json) で接続中...")
        return gspread.oauth(
            credentials_filename=client_secret_file,
            authorized_user_filename="authorized_user.json",
        )

    # 4. 認証情報が見つからない場合の案内メッセージ
    raise FileNotFoundError(
        "Google スプレッドシート API の認証情報が見つかりません。\n\n"
        "※ Google Sheets API (v4) は、スプレッドシートの共有設定が「リンクを知っている全員」であっても\n"
        "   Python API 経由でアクセスする場合はセキュリティの仕様により Google 認証（トークン）が必要です。\n\n"
        "【対処法 (以下のいずれかを実施してください)】\n"
        "1. サービスアカウント鍵 (service_account.json) をプロジェクト直下に配置する（推奨）\n"
        "2. OAuth クライアント ID (client_secret.json) を配置してブラウザ認証する\n"
        "3. .env ファイルの GOOGLE_SERVICE_ACCOUNT_JSON に JSON 文字列を設定する"
    )


def update_worksheet(spreadsheet: gspread.Spreadsheet, sheet_name: str, rows: List[List[Any]]) -> None:
    """指定ワークシートにデータ上書き保存（数値型として書き込み）"""
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        print(f"[INFO] ワークシート '{sheet_name}' が見つからないため、新規作成します。")
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=max(len(rows) + 10, 100),
            cols=max(len(rows[0]) + 5 if rows else 20, 20),
        )

    # データのクリアと新データの更新（数値型として書き込むため value_input_option="USER_ENTERED" を指定）
    worksheet.clear()
    if rows:
        worksheet.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
    print(f"[SUCCESS] ワークシート '{sheet_name}' に {len(rows)} 行のデータを正常に書き込みました！ (数値型変換適用)")


def main():
    print("============================================================")
    print("       AutoTicket - Teket & R7 自動開始")
    print("============================================================")

    # 1. Teket から CSV をダウンロード
    print("\n--- [STEP 1] Teket (teket.jp) CSV ダウンロード ---")
    teket_csv_path: Optional[str] = None
    try:
        teket_client = TeketClient()
        if teket_client.ensure_logged_in():
            teket_csv_path = teket_client.download_order_csv()
    except Exception as e:
        print(f"[ERROR] Teket の処理中にエラーが発生しました: {e}")

    # 2. R7 から CSV をダウンロード
    print("\n--- [STEP 2] R7 Ticket (tools.r7ticket.jp) CSV ダウンロード ---")
    r7_csv_path: Optional[str] = None
    try:
        r7_client = R7Client()
        if r7_client.ensure_logged_in():
            r7_csv_path = r7_client.download_booking_csv()
    except Exception as e:
        print(f"[ERROR] R7 Ticket の処理中にエラーが発生しました: {e}")

    # 3. Google スプレッドシートへの書き込み
    if not SPREADSHEET_URL:
        print("\n[WARNING] .env に SPREADSHEET_URL が設定されていないため、スプレッドシートへの書き込みをスキップします。")
        return

    print(f"\n--- [STEP 3] Google スプレッドシート更新 ---")
    print(f"対象 URL: {SPREADSHEET_URL}")

    try:
        gc = get_gspread_client()
        spreadsheet = gc.open_by_url(SPREADSHEET_URL)

        # Teket シート更新
        if teket_csv_path and os.path.exists(teket_csv_path):
            print("\n[INFO] Teket CSV データを読み込んで 'Teket' シートに書き込んでいます...")
            teket_rows = read_csv_rows(teket_csv_path)
            update_worksheet(spreadsheet, "Teket", teket_rows)
        else:
            print("[WARNING] Teket CSV が存在しないため、'Teket' シートの更新をスキップします。")

        # R7 シート更新
        if r7_csv_path and os.path.exists(r7_csv_path):
            print("\n[INFO] R7 CSV データを読み込んで 'R7' シートに書き込んでいます...")
            r7_rows = read_csv_rows(r7_csv_path)
            update_worksheet(spreadsheet, "R7", r7_rows)
        else:
            print("[WARNING] R7 CSV が存在しないため、'R7' シートの更新をスキップします。")

        print("\n============================================================")
        print(" [SUCCESS] 全工程（CSVダウンロード ＋ スプレッドシート反映）が完了しました！")
        print("============================================================")

    except FileNotFoundError as fnf_err:
        print(f"\n[AUTHENTICATION NOTICE]\n{fnf_err}")
    except Exception as e:
        print(f"\n[ERROR] Google スプレッドシート更新中にエラーが発生しました: {e}")


if __name__ == "__main__":
    main()
