"""配置加载 / 校验 / 来源标注的离线测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import Config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def _config(self, text: str) -> Config:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False,
                                          encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Config.load(tmp.name)

    def test_extra_file_overrides(self):
        cfg = self._config(
            "[quality]\nmax_height = 1080\n"
            "[naming]\ndefault = \"{platform}_{id}_{index}\"\n"
        )
        self.assertEqual(cfg.max_height, 1080)
        self.assertIn("file:", cfg.source_of("quality.max_height"))

    def test_validate_ok(self):
        cfg = self._config("[quality]\nmax_height = 1080\n")
        self.assertEqual(cfg.validate(), [])

    def test_validate_bad_height(self):
        cfg = self._config("[quality]\nmax_height = 9999\n")
        errors = cfg.validate()
        self.assertTrue(any("max_height" in error for error in errors))

    def test_validate_unknown_var(self):
        cfg = self._config("[naming]\ndefault = \"{platform}_{unknown}_{id}\"\n")
        errors = cfg.validate()
        self.assertTrue(any("未知变量" in error for error in errors))

    def test_effective_lines_have_sources(self):
        lines = Config.load().effective_lines()
        self.assertTrue(any("# default" in line or "# file:" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
