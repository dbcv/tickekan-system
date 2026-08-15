import os
import time
import json
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs
from curl_cffi import requests
from dotenv import load_dotenv

# .env ファイルからの環境変数ロード
load_dotenv()

FIREBASE_API_KEY = "AIzaSyDiiv8_mZjoh0W9Nz-WkY6zjEPL429qeBA"
FIREBASE_SEND_OOB_CODE_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={FIREBASE_API_KEY}"
FIREBASE_SIGN_IN_WITH_EMAIL_LINK_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithEmailLink?key={FIREBASE_API_KEY}"
MEJIRO_BASE_URL = "https://mejiro2.retro-ink.com/beeapi2/ticketa/v1/"
R7_BASE_URL = "https://tools.r7ticket.jp/"


TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


class R7Client:
    """R7 Ticket (tools.r7ticket.jp) へのメール認証ログインおよびセッション管理を行うクライアント"""

    def __init__(
        self,
        email: Optional[str] = None,
        cookie_file: Optional[str] = None,
    ):
        self.email = email or os.getenv("R7_EMAIL")
        self.cookie_file = cookie_file or os.path.join(TEMP_DIR, "r7_cookies.json")

        if not self.email:
            raise ValueError(
                "メールアドレスが設定されていません。\n"
                ".env ファイルに R7_EMAIL を設定するか、R7Client(email=...) で指定してください。"
            )

        # Cloudflare / WAF 対策として Firefox を偽装したセッションの生成
        self.session = requests.Session(impersonate="firefox")
        self.user_id: Optional[str] = None
        self.api_token: Optional[str] = None
        self.is_logged_in = False

    def save_cookies(self) -> None:
        """現在のセッションCookieおよびAPIトークン/ユーザー情報をファイルに保存する"""
        try:
            cookies_dict = self.session.cookies.get_dict()
            data = {
                "user_id": self.user_id,
                "api_token": self.api_token,
                "email": self.email,
                "cookies": cookies_dict,
                "updated_at": time.time(),
            }
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[INFO] R7 ログイン状態(Cookie/Token)を {self.cookie_file} に保存しました。")
        except Exception as e:
            print(f"[WARNING] Cookieの保存に失敗しました: {e}")

    def load_cookies(self) -> bool:
        """保存されたファイルからセッションCookieおよびAPIトークン/ユーザー情報を読み込む"""
        if not os.path.exists(self.cookie_file):
            return False
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.user_id = data.get("user_id")
            self.api_token = data.get("api_token")
            cookies_dict = data.get("cookies", {})

            for name, value in cookies_dict.items():
                self.session.cookies.set(name, value)

            return bool(self.user_id)
        except Exception as e:
            print(f"[WARNING] Cookieの読み込みに失敗しました: {e}")
            return False


    def _get_common_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://tools.r7ticket.jp",
            "Referer": "https://tools.r7ticket.jp/",
        }

    def request_login_email(self, email: Optional[str] = None) -> bool:
        """Firebase Auth REST API を使用してログイン用認証メールの送信をリクエストする"""
        target_email = email or self.email
        print(f"[INFO] {target_email} 宛てにログインメールの送信を要求中...")

        payload = {
            "requestType": "EMAIL_SIGNIN",
            "email": target_email,
            "continueUrl": "https://tools.r7ticket.jp/mail/new",
            "canHandleCodeInApp": True,
        }

        try:
            res = self.session.post(
                FIREBASE_SEND_OOB_CODE_URL,
                json=payload,
                headers=self._get_common_headers(),
            )
            if res.status_code == 200:
                print(f"[SUCCESS] {target_email} 宛てにログインメールを送信しました。")
                return True
            else:
                print(f"[ERROR] メール送信失敗: Status {res.status_code}, Response: {res.text}")
                return False
        except Exception as e:
            print(f"[ERROR] メール送信中にエラーが発生しました: {e}")
            return False

    @staticmethod
    def extract_oob_code(url_or_code: str) -> Optional[str]:
        """入力された文字列（URLまたはコード）から oobCode を抽出する"""
        url_or_code = url_or_code.strip()
        if not url_or_code:
            return None

        # 1. URL形式の場合: oobCode=... パラメータの抽出
        if "oobCode=" in url_or_code:
            parsed = urlparse(url_or_code)
            params = parse_qs(parsed.query)
            if "oobCode" in params:
                return params["oobCode"][0]

            # URLエンコードされた形式やハッシュ(#)以降に含まれる場合の正規表現抽出
            match = re.search(r"[?&#]oobCode=([^&]+)", url_or_code)
            if match:
                return match.group(1)

        # 2. クエリパラメータ無しの単体コード形式の場合
        return url_or_code

    def verify_email_link(self, email: str, oob_code: str) -> Optional[Dict[str, Any]]:
        """Firebase Auth REST API に oobCode を送信して認証を完了し UserId (localId) を取得する"""
        print("[INFO] Firebase Auth で認証コード (oobCode) を検証中...")
        payload = {
            "email": email,
            "oobCode": oob_code,
        }

        try:
            res = self.session.post(
                FIREBASE_SIGN_IN_WITH_EMAIL_LINK_URL,
                json=payload,
                headers=self._get_common_headers(),
            )
            if res.status_code == 200:
                data = res.json()
                print(f"[SUCCESS] Firebase 認証成功! (UserId: {data.get('localId')})")
                return data
            else:
                print(f"[ERROR] Firebase 認証検証失敗: Status {res.status_code}, Response: {res.text}")
                return None
        except Exception as e:
            print(f"[ERROR] Firebase 認証中にエラーが発生しました: {e}")
            return None

    def authenticate_mejiro(self, user_id: str) -> bool:
        """R7 Mejiro2 バックエンド API に UserId を送信し、セッション/APIトークンを確立する"""
        print(f"[INFO] R7 バックエンド (Mejiro2) でトークンを発行・セッション接続中...")
        url = f"{MEJIRO_BASE_URL}token/get"
        payload = {"UserId": user_id}

        try:
            res = self.session.post(
                url,
                json=payload,
                headers=self._get_common_headers(),
            )
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    self.user_id = user_id
                    self.api_token = data.get("token")
                    self.is_logged_in = True
                    print(f"[SUCCESS] R7 Ticket バックエンドセッション確立成功！ (Token: {self.api_token})")
                    return True
                else:
                    print(f"[ERROR] R7 バックエンド認証失敗 (Response: {data})")
                    return False
            else:
                print(f"[ERROR] R7 バックエンド認証失敗: Status {res.status_code}, Response: {res.text}")
                return False
        except Exception as e:
            print(f"[ERROR] R7 バックエンド接続中にエラーが発生しました: {e}")
            return False

    def verify_session(self) -> bool:
        """保存されたユーザーIDから API トークンを再取得・検証する"""
        if not self.user_id:
            return False

        url = f"{MEJIRO_BASE_URL}token/get"
        payload = {"UserId": self.user_id}

        try:
            res = self.session.post(
                url,
                json=payload,
                headers=self._get_common_headers(),
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("ok"):
                    self.api_token = data.get("token")
                    self.is_logged_in = True
                    # トークンを最新情報に更新保存
                    self.save_cookies()
                    return True
            return False
        except Exception:
            return False


    def login(self, manual_url_or_code: Optional[str] = None, force_relogin: bool = False) -> bool:
        """
        ログイン処理を行う。
        force_relogin=False の場合、まず保存済み Cookie を読み込んでセッションを検証し、
        有効であればメール送信を行わずに既存セッションでログインを完了します。
        """
        print("=== R7 Ticket ログイン処理開始 ===")

        # 1. 強制再ログインでない場合、保存済み Cookie の検証を実施
        if not force_relogin:
            if self.load_cookies():
                print(f"[INFO] 保存されたCookieファイル ({self.cookie_file}) を検証中...")
                if self.verify_session():
                    print("[SUCCESS] 保存されたCookieでログイン状態の継続を確認しました。（再ログイン省略）")
                    return True
                else:
                    print("[INFO] 保存済みCookieの有効期限が切れているため、新規ログインを実行します。")

        # 2. 認証メールの送信
        if not self.request_login_email():
            print("[ERROR] メール送信に失敗したため、ログインを中止します。")
            return False

        # 2. CLIでのURL入力プロンプト
        url_input = manual_url_or_code
        if not url_input:
            print("\n------------------------------------------------------------")
            print(f"メールアドレス ({self.email}) に届いたログインURLをご確認ください。")
            print("------------------------------------------------------------")
            url_input = input("[INPUT REQUIRED] メール内のログインURLを貼り付けてEnterを押してください: ")

        oob_code = self.extract_oob_code(url_input)
        if not oob_code:
            print("[ERROR] 入力されたURL/コードから oobCode を抽出できませんでした。")
            return False

        # 3. Firebase Auth の検証
        auth_data = self.verify_email_link(self.email, oob_code)
        if not auth_data or "localId" not in auth_data:
            print("[ERROR] Firebase Auth 認証に失敗しました。")
            return False

        user_id = auth_data["localId"]

        # 4. R7 Mejiro2 バックエンド認証
        if not self.authenticate_mejiro(user_id):
            print("[ERROR] R7 バックエンドセッションの確立に失敗しました。")
            return False

        # 5. Cookie / トークンの永続化保存
        self.save_cookies()
        print("=== R7 Ticket ログイン完了 ===")
        return True

    def ensure_logged_in(self) -> bool:
        """
        ログイン状態を保証する。
        保存済みCookieが存在し有効であればログイン処理をスキップし、
        無効または未保存の場合のみメールログインを実行してCookieを自動保存する。
        """
        if self.is_logged_in:
            return True

        # 1. 保存済み Cookie の読み込みと検証
        if self.load_cookies():
            print(f"[INFO] 保存されたCookieファイル ({self.cookie_file}) を検証中...")
            if self.verify_session():
                print("[SUCCESS] 保存されたCookieでログイン状態の継続を確認しました。（再ログイン省略）")
                return True
            else:
                print("[INFO] 保存済みCookieの有効期限が切れているため、再ログインを実行します。")

        # 2. 新規ログインを実行
        return self.login()

    def download_booking_csv(
        self,
        stage_id: Optional[str] = None,
        output_file: Optional[str] = None,
        search_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        指定された StageId (または環境変数 R7_STAGE_ID) の予約一覧 CSV をダウンロードする。
        """
        if not self.ensure_logged_in():
            print("[ERROR] ログインしていないため CSV ダウンロードを中止します。")
            return None

        target_stage_id = stage_id or os.getenv("R7_STAGE_ID") or "d7j07pmicnmdlrtjkqd0"
        url = f"{MEJIRO_BASE_URL}booking/download"

        default_search_booking = {
            "FormName": "",
            "TicketCode": "",
            "SeatId": 0,
            "Name": "",
            "Email": "",
            "Checked": "",
            "Tel": "",
            "Contact": "",
            "Payment": "",
            "PaymentTypeId": "",
            "Canceled": True,
            "P": 1,
        }
        if search_params:
            default_search_booking.update(search_params)

        payload = {
            "StageId": target_stage_id,
            "SearchBooking": default_search_booking,
            "Token": self.api_token,
        }

        print(f"[INFO] StageId: {target_stage_id} の予約一覧 CSV をダウンロード中...")
        try:
            res = self.session.post(
                url,
                json=payload,
                headers=self._get_common_headers(),
            )
            if res.status_code == 200:
                out_path = output_file or os.path.join(TEMP_DIR, f"order_{target_stage_id}.csv")
                with open(out_path, "wb") as f:
                    f.write(res.content)
                print(f"[SUCCESS] CSVを正常にダウンロード保存しました: {out_path} ({len(res.content)} bytes)")
                return out_path
            else:
                print(f"[ERROR] CSVダウンロード失敗: Status {res.status_code}, Response: {res.text}")
                return None
        except Exception as e:
            print(f"[ERROR] CSVダウンロード中にエラーが発生しました: {e}")
            return None


if __name__ == "__main__":
    try:
        client = R7Client()
        if client.ensure_logged_in():
            print("\n[RESULT] R7 Client ログイン検証に成功しました！")
            csv_path = client.download_booking_csv()
            if csv_path:
                print(f"[RESULT] 予約一覧 CSV をダウンロードしました: {csv_path}")
        else:
            print("\n[RESULT] R7 Client ログインに失敗しました。")
    except Exception as err:
        print(f"\n[FATAL] エラーが発生しました: {err}")

