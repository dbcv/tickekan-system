"""
i18n (多言語化・国際化) 基盤モジュール
TextID をキーとした多言語翻訳・テキスト解決を提供します。
"""

import os
import json
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCALES_DIR = os.path.join(BASE_DIR, "locales")

_translations_cache: Dict[str, Dict[str, Any]] = {}
DEFAULT_LANG = "ja"


def load_locale(lang: str = DEFAULT_LANG) -> Dict[str, Any]:
    """指定された言語の翻訳JSONファイルを読み込みキャッシュする"""
    if lang in _translations_cache:
        return _translations_cache[lang]

    filepath = os.path.join(LOCALES_DIR, f"{lang}.json")
    if not os.path.exists(filepath):
        # 指定言語ファイルが存在しない場合は ja をフォールバック
        if lang != DEFAULT_LANG:
            return load_locale(DEFAULT_LANG)
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            _translations_cache[lang] = data
            return data
    except Exception as e:
        print(f"[WARN] Failed to load locale '{lang}': {e}")
        return {}


def get_nested_value(data: Dict[str, Any], path: str) -> Optional[Any]:
    """ドット記法（例: 'dashboard.tabs.console'）で階層辞書から値を取得"""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def t(key: str, default: Optional[str] = None, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """
    TextID に対応するテキストを取得し、プレースホルダーを置換する。

    :param key: TextID (例: 'login.title', 'status.page_title')
    :param default: キーが存在しなかった場合のデフォルト値
    :param lang: 言語コード ('ja' など)
    :param kwargs: 文字列フォーマット用の変数 (例: name="山田太郎")
    :return: 解決された文字列
    """
    locale_data = load_locale(lang)
    val = get_nested_value(locale_data, key)

    if val is None:
        val = default if default is not None else key

    if isinstance(val, str) and kwargs:
        try:
            val = val.format(**kwargs)
        except Exception:
            pass

    return str(val)


def get_translations(lang: str = DEFAULT_LANG) -> Dict[str, Any]:
    """言語辞書データを取得"""
    return load_locale(lang)


def reload_locales():
    """キャッシュをクリアして再読み込み"""
    global _translations_cache
    _translations_cache.clear()
