"""链接抽取的离线测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.urls import iter_urls  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_concat_urls(self):
        text = (
            "https://www.google.com.hk/search?q=1"
            "https://www.google.com.hk/search?q=2"
            "https://www.google.com.hk/search?q=3"
            "https://www.google.com.hk/search?q=4"
        )
        urls = iter_urls([text])
        self.assertEqual(len(urls), 4)
        self.assertEqual(urls[0], "https://www.google.com.hk/search?q=1")
        self.assertEqual(urls[-1], "https://www.google.com.hk/search?q=4")

    def test_concat_identical_urls_are_deduped(self):
        text = "https://a.com/xhttps://a.com/x"
        self.assertEqual(iter_urls([text]), ["https://a.com/x"])

    def test_share_text_with_chinese_suffix(self):
        text = "3.45 复制打开抖音，看看【某作者】的作品 https://v.douyin.com/abc/ 复制此链接"
        self.assertEqual(iter_urls([text]), ["https://v.douyin.com/abc/"])

    def test_trailing_punctuation(self):
        text = "看这个（https://x.com/foo/status/123），还有 https://x.com/foo/status/456。"
        self.assertEqual(
            iter_urls([text]),
            ["https://x.com/foo/status/123", "https://x.com/foo/status/456"],
        )

    def test_html_entity_and_query(self):
        text = "https://x.com/a/status/1?a=1&amp;s=20"
        self.assertEqual(iter_urls([text]), ["https://x.com/a/status/1?a=1&s=20"])

    def test_dedupe(self):
        text = "https://x.com/a/status/1 https://x.com/a/status/1"
        self.assertEqual(iter_urls([text]), ["https://x.com/a/status/1"])

    def test_ignore_meaningless_args(self):
        self.assertEqual(iter_urls(["随便一段文字", "", "12345"]), [])

    def test_multiple_arguments(self):
        urls = iter_urls(["https://x.com/a/status/1", "无意义", "https://x.com/a/status/2"])
        self.assertEqual(urls, ["https://x.com/a/status/1", "https://x.com/a/status/2"])


if __name__ == "__main__":
    unittest.main()
