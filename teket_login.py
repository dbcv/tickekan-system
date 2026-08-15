import os
import time
import json
from typing import Optional
from urllib.parse import quote
from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv

# .env ファイルからの環境変数ロード
load_dotenv()

LOGIN_URL = "https://teket.jp/login"
MYPAGE_URL = "https://teket.jp/mypage/profile"


TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)


class TeketClient:
    """Teket (teket.jp) へのログインおよび認証済みセッションを管理するクライアント"""

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        cookie_file: Optional[str] = None,
    ):
        self.email = email or os.getenv("TEKET_EMAIL")
        self.password = password or os.getenv("TEKET_PASSWORD")
        self.cookie_file = cookie_file or os.path.join(TEMP_DIR, "teket_cookies.json")

        if not self.email or not self.password:
            raise ValueError(
                "メールアドレスまたはパスワードが設定されていません。\n"
                ".env ファイルに TEKET_EMAIL と TEKET_PASSWORD を設定するか、TeketClient(email, password) で指定してください。"
            )

        # Cloudflare / WAF 対策として Firefox を偽装したセッションの生成
        self.session = requests.Session(impersonate="firefox")
        self.is_logged_in = False

    def save_cookies(self) -> None:
        """現在のセッションCookieをファイルに保存する"""
        try:
            cookies_dict = self.session.cookies.get_dict()
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(cookies_dict, f, indent=2)
            print(f"[INFO] ログイン状態(Cookie)を {self.cookie_file} に保存しました。")
        except Exception as e:
            print(f"[WARNING] Cookieの保存に失敗しました: {e}")

    def load_cookies(self) -> bool:
        """保存されたファイルからセッションCookieを読み込む"""
        if not os.path.exists(self.cookie_file):
            return False
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies_dict = json.load(f)
            for name, value in cookies_dict.items():
                self.session.cookies.set(name, value)
            return True
        except Exception as e:
            print(f"[WARNING] Cookieの読み込みに失敗しました: {e}")
            return False

    def ensure_logged_in(self) -> bool:
        """
        ログイン状態を保証する。
        保存済みCookieが存在し有効であればログイン処理をスキップし、
        無効または未保存の場合のみログインを実行してCookieを自動保存する。
        """
        if self.is_logged_in:
            return True

        # 1. 保存済み Cookie の読み込みと検証
        if self.load_cookies():
            print(f"[INFO] 保存されたCookieファイル ({self.cookie_file}) を検証中...")
            res = self.session.get(MYPAGE_URL, headers=self._get_headers_get())
            if res.status_code == 200 and "login" not in res.url:
                self.is_logged_in = True
                print("[SUCCESS] 保存されたCookieでログイン状態の継続を確認しました。（再ログイン省略）")
                return True
            else:
                print("[INFO] 保存済みCookieの有効期限が切れているため、再ログインを実行します。")

        # 2. 新規ログインを実行して Cookie 保存
        if self.login():
            self.save_cookies()
            return True

        return False

    def _get_headers_get(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Priority": "u=0, i",
        }

    def _get_headers_post(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Priority": "u=0, i",
            "Referer": LOGIN_URL,
            "Origin": "https://teket.jp",
        }

    def login(self) -> bool:
        """Teketにログインを試行する"""
        print("[INFO] 1. ログインページへアクセスして CSRF トークンを取得中...")
        res_get = self.session.get(LOGIN_URL, headers=self._get_headers_get())

        if res_get.status_code != 200:
            print(f"[ERROR] ログインページの取得に失敗しました (Status: {res_get.status_code})")
            return False

        soup = BeautifulSoup(res_get.text, "html.parser")

        # パスワード入力欄を持つ対象のログインフォームを特定
        login_form = None
        for form in soup.find_all("form"):
            if form.find("input", {"name": "password"}):
                login_form = form
                break

        if not login_form:
            print("[ERROR] ログインフォームが見つかりませんでした。")
            return False

        csrf_token_elem = login_form.find("input", {"name": "_csrfToken"})
        token_fields_elem = login_form.find("input", {"name": "_Token[fields]"})
        token_unlocked_elem = login_form.find("input", {"name": "_Token[unlocked]"})

        if not csrf_token_elem:
            print("[ERROR] CSRFトークンが見つかりませんでした。")
            return False

        csrf_token = csrf_token_elem.get("value", "")
        token_fields = token_fields_elem.get("value", "") if token_fields_elem else ""
        token_unlocked = token_unlocked_elem.get("value", "") if token_unlocked_elem else ""

        print(f"[SUCCESS] CSRFトークン取得成功: {csrf_token[:20]}...")

        # 生のPOSTボディ構築 (URLエンコード)
        body_str = (
            f"_csrfToken={quote(csrf_token, safe='')}"
            f"&email={quote(self.email, safe='')}"
            f"&password={quote(self.password, safe='')}"
            f"&remember=0"
            f"&remember=1"
            f"&from_pin_code_input="
            f"&_Token%5Bfields%5D={quote(token_fields, safe='')}"
            f"&_Token%5Bunlocked%5D={quote(token_unlocked, safe='')}"
        )

        time.sleep(1)
        print("[INFO] 2. ログイン処理を実行中...")

        res_post = self.session.post(
            LOGIN_URL,
            data=body_str.encode("utf-8"),
            headers=self._get_headers_post(),
            allow_redirects=True,
        )

        print(f"[INFO] レスポンスステータス: {res_post.status_code}")
        print(f"[INFO] 遷移後のURL: {res_post.url}")

        if "login" not in res_post.url and res_post.status_code == 200:
            self.is_logged_in = True
            print("\n[SUCCESS] ログイン成功！ 認証を完了しました。")
            self.save_cookies()
            return True
        else:
            print("\n[ERROR] ログイン失敗")
            error_soup = BeautifulSoup(res_post.text, "html.parser")
            error_msg = (
                error_soup.find("div", class_="error-message")
                or error_soup.find("div", class_="alert")
                or error_soup.find("p", class_="error")
            )
            if error_msg:
                print(f"[ERROR] 画面上のメッセージ: {error_msg.text.strip()}")
            return False

    def verify_auth(self) -> bool:
        """ログイン状態の検証 (マイページへアクセス)"""
        if not self.is_logged_in:
            return False
        res = self.session.get(MYPAGE_URL, headers=self._get_headers_get())
        return res.status_code == 200 and "login" not in res.url

    def get(self, url: str) -> requests.Response:
        """ログイン済みのセッションで指定されたURLへアクセスする"""
        if not self.ensure_logged_in():
            raise RuntimeError("ログイン状態を確保できなかったため、アクセスできません。")

        headers = self._get_headers_get()
        headers["Referer"] = "https://teket.jp/"
        return self.session.get(url, headers=headers)

    def post(self, url: str, data: dict, referer: Optional[str] = None) -> requests.Response:
        """ログイン済みのセッションでフォームデータ(dict)をPOST送信する"""
        if not self.ensure_logged_in():
            raise RuntimeError("ログイン状態を確保できなかったため、アクセスできません。")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://teket.jp",
            "Referer": referer or "https://teket.jp/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        body_parts = [f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in data.items()]
        body_str = "&".join(body_parts)

        return self.session.post(
            url,
            data=body_str.encode("utf-8"),
            headers=headers,
            allow_redirects=True,
        )

    def download_order_csv(
        self,
        group_id: Optional[str] = None,
        event_id: Optional[str] = None,
        output_filepath: Optional[str] = None,
        max_wait_seconds: int = 30,
    ) -> str:
        """
        注文情報のCSVファイルを予約・生成待ち・取得して保存する

        :param group_id: グループID (未指定の場合は .env から取得)
        :param event_id: イベントID (未指定の場合は .env から取得)
        :param output_filepath: 出力先のファイルパス
        :param max_wait_seconds: 生成完了待ちの最大待機秒数
        :return: 保存したファイルパス
        """
        group_id = group_id or os.getenv("TEKET_GROUP_ID", "2750")
        event_id = event_id or os.getenv("TEKET_EVENT_ID", "68903")

        order_url = f"https://teket.jp/group/{group_id}/order/{event_id}"
        print(f"[INFO] 注文管理画面からフォーム情報を取得中: {order_url}")
        res_order = self.get(order_url)

        soup = BeautifulSoup(res_order.text, "html.parser")
        form_req = soup.find("form", {"id": "fileDownloadsRequest"})
        form_prog = soup.find("form", {"id": "fileDownloadsProgress"})

        if not form_req or not form_prog:
            raise ValueError("必要なフォーム (#fileDownloadsRequest / #fileDownloadsProgress) が見つかりませんでした。")

        # 1. request.json でダウンロード予約
        data_req = {inp.get("name"): inp.get("value") or "" for inp in form_req.find_all("input") if inp.get("name")}
        url_req = f"https://teket.jp/group/{group_id}/file-download/request.json"

        print("[INFO] 1. ファイルダウンロード予約 (request.json) を送信中...")
        res_req = self.post(url_req, data=data_req, referer=order_url)
        resp_json = res_req.json()

        if resp_json.get("status") != "OK":
            raise RuntimeError(f"予約レスポンスエラー: {resp_json}")

        file_download_id = resp_json.get("file_download_id")
        if not file_download_id:
            raise RuntimeError("file_download_id が取得できませんでした。")

        print(f"[SUCCESS] file_download_id: {file_download_id} 発行完了")

        # 2. progress.json でファイル生成完了をポーリング待機
        data_prog = {inp.get("name"): inp.get("value") or "" for inp in form_prog.find_all("input") if inp.get("name")}
        data_prog["file_download_id"] = str(file_download_id)
        url_prog = f"https://teket.jp/group/{group_id}/file-download/progress.json"

        print(f"[INFO] 2. ファイル生成進捗をポーリング中...")
        start_time = time.time()
        completed = False

        while (time.time() - start_time) < max_wait_seconds:
            time.sleep(2)
            res_p = self.post(url_prog, data=data_prog, referer=order_url)
            p_json = res_p.json()
            if str(p_json.get("completed")) == "1":
                completed = True
                print("[SUCCESS] ファイル生成が完了しました。")
                break

        if not completed:
            raise TimeoutError("ファイル生成の完了タイムアウトを超過しました。")

        # 3. CSV ダウンロード実行
        download_url = f"https://teket.jp/group/{group_id}/order/download/{event_id}?file_download_id={file_download_id}"
        print(f"[INFO] 3. CSV データをダウンロード中: {download_url}")

        headers = self._get_headers_get()
        headers["Referer"] = order_url
        res_csv = self.session.get(download_url, headers=headers)

        if res_csv.status_code != 200:
            raise RuntimeError(f"CSVダウンロードに失敗しました (Status: {res_csv.status_code})")

        # 4. ファイル保存
        if not output_filepath:
            output_filepath = os.path.join(TEMP_DIR, f"order_{event_id}.csv")

        with open(output_filepath, "wb") as f:
            f.write(res_csv.content)

        print(f"[SUCCESS] CSVファイルを正常に保存しました: {output_filepath} ({len(res_csv.content)} bytes)")
        return output_filepath


if __name__ == "__main__":
    try:
        client = TeketClient()
        if client.ensure_logged_in():
            # 引数を省略すると .env から TEKET_GROUP_ID と TEKET_EVENT_ID が自動使用されます
            csv_path = client.download_order_csv()
            print(f"[SUCCESS] 全工程完了！ ダウンロードファイル: {csv_path}")
    except Exception as e:
        print(f"[ERROR] エラーが発生しました: {e}")