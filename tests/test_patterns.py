"""文件名模板正反向、字符清理、网址重建的离线测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import naming, patterns  # noqa: E402


class SanitizeTests(unittest.TestCase):
    def test_remove_invalid_chars_not_replace(self):
        self.assertEqual(naming.sanitize('a:b*c?"<>|d'), "abcd")

    def test_remove_emoji(self):
        self.assertEqual(naming.sanitize("作者🎵名字"), "作者名字")

    def test_keep_chinese_and_space(self):
        self.assertEqual(naming.sanitize("小 红"), "小 红")

    def test_empty(self):
        self.assertEqual(naming.sanitize('///:::'), "untitled")

    def test_render_single_omits_index(self):
        variables = {"platform": "twitter", "author": "foo", "id": "123"}
        self.assertEqual(
            naming.render("{platform}_{author}_{id}_{index}", variables, is_multi=False),
            "twitter_foo_123",
        )


class ParseTests(unittest.TestCase):
    def test_twitter(self):
        fields = patterns.parse_name("twitter_foo_123456789")
        self.assertIsNotNone(fields)
        self.assertEqual(fields["platform"], "twitter")
        self.assertEqual(fields["author"], "foo")
        self.assertEqual(fields["id"], "123456789")

    def test_author_with_underscore(self):
        fields = patterns.parse_name("twitter_foo_bar_123456789")
        self.assertEqual(fields["author"], "foo_bar")
        self.assertEqual(fields["id"], "123456789")

    def test_xhs_with_space(self):
        fields = patterns.parse_name("xhs_小 红_6af47822000000002501c443")
        self.assertEqual(fields["platform"], "xhs")
        self.assertEqual(fields["author"], "小 红")
        self.assertEqual(fields["id"], "6af47822000000002501c443")

    def test_tiktok_handle(self):
        fields = patterns.parse_name("tiktok_bodikaidenandi_7667479697651010823")
        self.assertEqual(fields["author"], "bodikaidenandi")
        self.assertEqual(fields["id"], "7667479697651010823")

    def test_positional_pattern(self):
        fields = patterns.parse_name("foo_123456", platform="twitter",
                                     extra_patterns=["{1}_{2}"])
        self.assertEqual(fields["author"], "foo")
        self.assertEqual(fields["id"], "123456")

    def test_multi_index(self):
        fields = patterns.parse_name("twitter_foo_123456_02")
        self.assertEqual(fields["index"], "02")
        self.assertEqual(fields["id"], "123456")

    def test_gallerydl_raw_requires_platform(self):
        self.assertIsNone(patterns.parse_name("1688357916741378050-F21yPdlasAAnhaP"))
        fields = patterns.parse_name("1688357916741378050-F21yPdlasAAnhaP",
                                     platform="twitter")
        self.assertEqual(fields["id"], "1688357916741378050")

    def test_telegram_without_id_fails(self):
        self.assertIsNone(patterns.parse_name("telegram_somechannel"))


class UrlTests(unittest.TestCase):
    def test_twitter_url(self):
        self.assertEqual(
            patterns.rebuild_url("twitter", {"id": "123"}),
            "https://x.com/i/status/123",
        )
        self.assertEqual(
            patterns.rebuild_url("twitter", {"author": "foo", "id": "123"}),
            "https://x.com/foo/status/123",
        )

    def test_xhs_url(self):
        self.assertEqual(
            patterns.rebuild_url("xhs", {"id": "abc"}),
            "https://www.xiaohongshu.com/explore/abc",
        )

    def test_tiktok_needs_author(self):
        self.assertIsNone(patterns.rebuild_url("tiktok", {"id": "123"}))
        self.assertEqual(
            patterns.rebuild_url("tiktok", {"author": "foo", "id": "123"}),
            "https://www.tiktok.com/@foo/video/123",
        )

    def test_telegram(self):
        self.assertIsNone(patterns.rebuild_url("telegram", {"id": "123"}))
        ok, reason = patterns.can_rebuild("telegram", {"id": "123"})
        self.assertFalse(ok)
        self.assertIn("频道", reason)


if __name__ == "__main__":
    unittest.main()
