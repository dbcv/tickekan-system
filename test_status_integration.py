#!/usr/bin/env python3
"""
status_service および Flask エンドポイントのテストスクリプト
"""
import os
import sys
import unittest
from status_service import status_service, format_number
from app import app

class TestStatusService(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()

    def test_format_number(self):
        self.assertEqual(format_number(1.0), 1)
        self.assertEqual(format_number("2.0"), 2)
        self.assertEqual(format_number(3.5), 3.5)
        self.assertEqual(format_number(0), 0)

    def test_validate_user(self):
        members = [
            {"NAME": "テスト太郎", "ID": "abc12345", "SN": "しろ太郎"},
            {"NAME": "山田花子", "ID": "xyz98765", "SN": "しろ花子"}
        ]
        # 正常
        valid, info = status_service.validate_user("テスト太郎", "abc12345", members)
        self.assertTrue(valid)
        self.assertEqual(info["NAME"], "テスト太郎")

        # ID違い
        valid, info = status_service.validate_user("テスト太郎", "wrong_id", members)
        self.assertFalse(valid)

        # 名前違い
        valid, info = status_service.validate_user("誰か", "abc12345", members)
        self.assertFalse(valid)

    def test_app_routes(self):
        # 存在しないユーザーでのアクセス (403 expected)
        res = self.app.get("/status/dummy_name/dummy_id")
        self.assertEqual(res.status_code, 403)
        self.assertIn("データが見つかりません", res.get_data(as_text=True))

        res_prefixed = self.app.get("/tickekan-system/status/dummy_name/dummy_id")
        self.assertEqual(res_prefixed.status_code, 403)

        # API版 403
        res_api = self.app.get("/api/status/dummy_name/dummy_id")
        self.assertEqual(res_api.status_code, 403)
        self.assertFalse(res_api.get_json()["success"])

        res_api_prefixed = self.app.get("/tickekan-system/api/status/dummy_name/dummy_id")
        self.assertEqual(res_api_prefixed.status_code, 403)
        self.assertFalse(res_api_prefixed.get_json()["success"])

    def test_multi_name_split(self):
        # status_service の集計ロジックのテスト
        mock_members = [{"NAME": "山田太郎", "ID": "taro123"}, {"NAME": "佐藤花子", "ID": "hanako456"}]
        mock_tickets = [
            {"名前": "山田太郎, 佐藤花子", "種別": "1ステ", "購入者": "共通ファン", "数": "2"},
            {"名前": "山田太郎", "種別": "2ステ", "購入者": "単独ファン", "数": "1"},
        ]

        import re
        from collections import defaultdict
        
        def calculate_for_user(target_name):
            grouped = defaultdict(float)
            for row in mock_tickets:
                raw_name_str = str(row.get("名前", "")).strip()
                names = [n.strip() for n in re.split(r'[,，]', raw_name_str) if n.strip()]
                if target_name in names:
                    count = float(row.get("数", 0)) / len(names)
                    grouped[(row["種別"], row["購入者"])] += count
            return sum(grouped.values()), grouped

        # 山田太郎: 2人の分 (2 / 2 = 1) + 単独分 (1) = 2枚
        taro_total, taro_grouped = calculate_for_user("山田太郎")
        self.assertEqual(taro_total, 2.0)
        self.assertEqual(taro_grouped[("1ステ", "共通ファン")], 1.0)
        self.assertEqual(taro_grouped[("2ステ", "単独ファン")], 1.0)

        # 佐藤花子: 2人の分 (2 / 2 = 1) = 1枚
        hanako_total, hanako_grouped = calculate_for_user("佐藤花子")
        self.assertEqual(hanako_total, 1.0)
        self.assertEqual(hanako_grouped[("1ステ", "共通ファン")], 1.0)


if __name__ == "__main__":
    unittest.main()
