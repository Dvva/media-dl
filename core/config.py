"""配置加载与合并。

优先级：内置默认 < config.toml < config.local.toml < 命令行参数
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

try:  # Python 3.11+ 内置
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 及以下
    import tomli as tomllib  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config.toml"
LOCAL_CONFIG = REPO_ROOT / "config.local.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典，override 优先。"""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def expand_path(value: str) -> Path:
    """展开 ~ 与环境变量，返回绝对 Path。"""
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


class Config:
    """配置对象，提供点号访问与路径展开。"""

    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, extra_path: str | None = None) -> "Config":
        data = _load_toml(DEFAULT_CONFIG)
        data = _deep_merge(data, _load_toml(LOCAL_CONFIG))
        if extra_path:
            data = _deep_merge(data, _load_toml(Path(extra_path)))
        return cls(data)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- 常用快捷属性 ----

    @property
    def output_dir(self) -> Path:
        return expand_path(self.get("general.output_dir", "~/media"))

    @property
    def proxy(self) -> str:
        # 配置优先，其次环境变量
        return (
            self.get("general.proxy")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or ""
        )

    @property
    def max_height(self) -> int:
        return int(self.get("quality.max_height", 720))

    @property
    def cover_mode(self) -> str:
        return str(self.get("cover.mode", "sidecar")).lower()

    @property
    def cover_enabled(self) -> bool:
        return bool(self.get("cover.enabled", True)) and self.cover_mode != "none"

    @property
    def naming_default(self) -> str:
        return str(self.get("naming.default", "{platform}_{id}_{index}"))

    @property
    def omit_index_when_single(self) -> bool:
        return bool(self.get("naming.omit_index_when_single", True))

    def naming_for(self, platform: str) -> str:
        """平台级模板优先，否则用全局默认。"""
        return str(self.get(f"naming.{platform}") or self.naming_default)

    @property
    def cookies_dir(self) -> Path:
        return expand_path(self.get("cookies.dir", "~/cookies"))

    def cookie_file(self, platform: str) -> Path | None:
        """返回该平台的 Netscape cookies 文件，不存在则 None。"""
        name = self.get(f"cookies.{platform}")
        candidate = expand_path(name) if name else self.cookies_dir / f"{platform}.txt"
        return candidate if candidate.exists() else None

    def enabled(self, platform: str) -> bool:
        return platform in (self.get("platforms.enabled") or [])

    def delay(self, platform: str) -> float:
        return float(self.get(f"platforms.{platform}.delay_sec", 0) or 0)
