"""批量输入 / doctor / 文件名解析的离线测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import batch, patterns  # noqa: E402
from core.config import Config  # noqa: E402


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mediadl_test_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.cfg = Config.load()

    def _touch(self, name: str) -> Path:
        path = self.tmp / name
        path.write_bytes(b"x")
        return path

    def test_describe_file(self):
        path = self._touch("twitter_foo_123456789.mp4")
        fields, reason = batch.describe_file(path, self.cfg)
        self.assertIsNone(reason)
        self.assertEqual(fields["id"], "123456789")

    def test_doctor_counts_unparsable(self):
        self._touch("twitter_foo_123456789.mp4")
        self._touch("xhs_小 红_6af47822000000002501c443.jpg")
        self._touch("telegram_somechannel.mp4")
        lines: list[str] = []
        counts = batch.doctor([str(self.tmp)], self.cfg, log=lines.append)
        self.assertEqual(counts.total, 3)
        self.assertEqual(counts.unparsable, 1)
        self.assertTrue(any("telegram_somechannel" in line for line in lines))

    def test_read_inputs_txt(self):
        listing = self.tmp / "list.txt"
        listing.write_text(
            "# 注释\n"
            "https://x.com/a/status/123456789\n"
            "twitter 9876543210\n"
            "随便一段没用的文字\n",
            encoding="utf-8",
        )
        inputs = batch.read_inputs([str(listing)], cfg=self.cfg,
                                   platform="twitter", log=lambda *_: None)
        urls = [item["url"] for item in inputs]
        self.assertIn("https://x.com/a/status/123456789", urls)
        self.assertTrue(any("9876543210" in url for url in urls))

    def test_collect_files_skips_trash(self):
        self._touch("twitter_foo_123.mp4")
        trash = self.tmp / ".trash" / "20260101"
        trash.mkdir(parents=True)
        (trash / "old.mp4").write_bytes(b"x")
        files = batch.collect_files([str(self.tmp)])
        self.assertEqual([path.name for path in files], ["twitter_foo_123.mp4"])

    def test_unparsable_reason(self):
        fields = patterns.parse_name("telegram_somechannel")
        self.assertIsNone(fields)


if __name__ == "__main__":
    unittest.main()
