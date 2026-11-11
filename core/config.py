"""配置加载与合并，并记录每个值的来源。

优先级：内置默认 < config.toml < config.local.toml < --config < 命令行参数
`--print-config` 会逐项标注 default / file:<名字> / cli。
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
CONFIG_FILE = REPO_ROOT / "config.toml"
EXAMPLE_FILE = REPO_ROOT / "config.example.toml"
LOCAL_CONFIG = REPO_ROOT / "config.local.toml"


DEFAULTS: dict[str, Any] = {
    "general": {
        "output_dir": "~/media",
        "proxy": "",
        "download_timeout": 60,
        "retries": 2,
        "log_dir": "~/.local/state/media-dl/logs",
        "lock_file": "~/.local/state/media-dl/.lock",
        "state_dir": "~/.local/state/media-dl",
    },
    "quality": {"max_height": 720},
    "cover": {
        "enabled": True,
        "embed_platforms": ["bilibili", "youtube"],
        "mode": "embed",
        "others_mode": "none",
    },
    "naming": {
        "default": "{platform}_{author}_{id}_{index}",
        "omit_index_when_single": True,
        "max_len": 120,
        "twitter": "twitter_{author}_{id}",
        "xhs": "xhs_{author}_{id}",
        "douyin": "douyin_{author}_{id}",
        "tiktok": "tiktok_{author}_{id}",
        "bilibili": "bilibili_{author}_{id}",
        "youtube": "youtube_{author}_{id}",
        "telegram": "telegram_{author}_{id}",
    },
    "urls": {
        "twitter": "https://x.com/i/status/{id}",
        "xhs": "https://www.xiaohongshu.com/explore/{id}",
        "douyin": "https://www.douyin.com/video/{id}",
        "tiktok": "https://www.tiktok.com/@{author}/video/{id}",
        "bilibili": "https://www.bilibili.com/video/{id}",
        "youtube": "https://www.youtube.com/watch?v={id}",
        "telegram": "https://t.me/{author}/{id}",
    },
    "patterns": {},
    "behavior": {
        "set_mtime": True,
        "overwrite": False,
        "backup_dir": "~/.local/state/media-dl/backup",
        "trash": "auto",
        "warn_unparsable": True,
        "first_run_notice": True,
        "probe_cache_ttl_days": 7,
    },
    "platforms": {
        "enabled": ["twitter", "xhs", "douyin", "tiktok", "bilibili", "telegram", "youtube"],
        "xhs": {"delay_sec": 3},
        "douyin": {"delay_sec": 1},
    },
    "cookies": {
        "dir": "~/cookies",
        "twitter": "",
        "xhs": "",
        "bilibili": "",
        "tiktok": "",
        "douyin": "",
        "youtube": "",
        "telegram": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _flatten(data: dict, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, dotted))
        else:
            result[dotted] = value
    return result


def _merge_with_sources(
    base: dict, override: dict, sources: dict[str, str], origin: str, prefix: str = ""
) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_with_sources(out[key], value, sources, origin, dotted)
        else:
            out[key] = value
            sources[dotted] = origin
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
    """配置对象，提供点号访问、来源标注与校验。"""

    def __init__(self, data: dict, sources: dict[str, str] | None = None,
                 files: list[Path] | None = None):
        self.data = data
        self.sources = sources or {}
        self.config_files = files or []
        self._proxy_override: str | None = None
        self.errors: list[str] = []

    @classmethod
    def load(cls, extra_path: str | None = None, *,
             overrides: dict[str, Any] | None = None) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        sources = {key: "default" for key in _flatten(DEFAULTS)}
        files: list[Path] = []

        base_file = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_FILE
        if base_file.exists():
            data = _merge_with_sources(data, _load_toml(base_file), sources,
                                       f"file:{base_file.name}")
            files.append(base_file)

        if LOCAL_CONFIG.exists():
            data = _merge_with_sources(data, _load_toml(LOCAL_CONFIG), sources,
                                       f"file:{LOCAL_CONFIG.name}")
            files.append(LOCAL_CONFIG)

        if extra_path:
            path = Path(extra_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(str(path))
            data = _merge_with_sources(data, _load_toml(path), sources,
                                       f"file:{path.name}")
            files.append(path)

        for dotted, value in (overrides or {}).items():
            if value is None:
                continue
            _set_dotted(data, dotted, value)
            sources[dotted] = "cli"

        return cls(data, sources, files)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def source_of(self, dotted: str) -> str:
        return self.sources.get(dotted, "default")

    def set_cli(self, dotted: str, value: Any) -> None:
        _set_dotted(self.data, dotted, value)
        self.sources[dotted] = "cli"

    # ---- 常用快捷属性 ----

    @property
    def output_dir(self) -> Path:
        return expand_path(self.get("general.output_dir", "~/media"))

    @property
    def state_dir(self) -> Path:
        return expand_path(self.get("general.state_dir", "~/.local/state/media-dl"))

    @property
    def backup_dir(self) -> Path:
        return expand_path(self.get("behavior.backup_dir",
                                    "~/.local/state/media-dl/backup"))

    @property
    def proxy(self) -> str:
        if self._proxy_override is not None:
            return self._proxy_override
        return (
            self.get("general.proxy")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or ""
        )

    def override_proxy(self, value: str) -> None:
        """运行期改写代理（探测到代理不可用时降级为直连）。"""
        self._proxy_override = value

    @property
    def max_height(self) -> int:
        return int(self.get("quality.max_height", 720))

    @property
    def cover_mode(self) -> str:
        return str(self.get("cover.mode", "sidecar")).lower()

    @property
    def cover_enabled(self) -> bool:
        return bool(self.get("cover.enabled", True))

    @property
    def set_mtime(self) -> bool:
        return bool(self.get("behavior.set_mtime", True))

    @property
    def overwrite(self) -> bool:
        return bool(self.get("behavior.overwrite", False))

    @property
    def trash_mode(self) -> str:
        return str(self.get("behavior.trash", "auto")).lower()

    @property
    def warn_unparsable(self) -> bool:
        return bool(self.get("behavior.warn_unparsable", True))

    def cover_mode_for(self, platform: str) -> str:
        """按平台决定封面策略。"""
        if not self.cover_enabled:
            return "none"
        listed = [str(p).lower() for p in (self.get("cover.embed_platforms") or [])]
        if platform.lower() in listed:
            return str(self.get("cover.mode", "embed")).lower()
        return str(self.get("cover.others_mode", "none")).lower()

    @property
    def naming_default(self) -> str:
        return str(self.get("naming.default", "{platform}_{author}_{id}_{index}"))

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

    # ---- 打印与校验 ----

    def effective_lines(self) -> list[str]:
        flat = _flatten(self.data)
        lines = []
        for key in sorted(flat):
            value = flat[key]
            if isinstance(value, str) and value == "":
                value = '""'
            lines.append(f"{key} = {value!r}   # {self.source_of(key)}")
        return lines

    def validate(self) -> list[str]:
        """返回错误列表；空列表表示通过。"""
        from core import patterns

        errors: list[str] = []
        known = set(patterns.PLATFORMS)
        enabled = self.get("platforms.enabled") or []
        for platform in enabled:
            if platform not in known:
                errors.append(f"platforms.enabled 里有未知平台：{platform}")

        height = self.get("quality.max_height")
        try:
            height = int(height)
            if not 144 <= height <= 4320:
                errors.append(f"quality.max_height 超出范围（144–4320）：{height}")
        except (TypeError, ValueError):
            errors.append(f"quality.max_height 不是整数：{height!r}")

        for name in ["default", *known]:
            template = self.get(f"naming.{name}")
            if not template:
                continue
            unknown = patterns.check_template(str(template))
            if unknown:
                errors.append(f"naming.{name} 含未知变量：{', '.join(unknown)}")

        for name in known:
            template = self.get(f"urls.{name}")
            if not template:
                continue
            if not str(template).lower().startswith(("http://", "https://")):
                errors.append(f"urls.{name} 不是 http(s) 链接模板")
                continue
            unknown = patterns.check_template(str(template))
            if unknown:
                errors.append(f"urls.{name} 含未知变量：{', '.join(unknown)}")

        proxy = str(self.get("general.proxy") or "")
        if proxy and "://" not in proxy:
            errors.append(f"general.proxy 缺少协议头（如 http://127.0.0.1:7890）：{proxy}")

        trash = str(self.get("behavior.trash") or "auto").lower()
        if trash not in {"auto", "recycle", "dir", "backup", "none"}:
            errors.append(f"behavior.trash 只能是 auto/recycle/dir/backup/none：{trash}")

        return errors


def _set_dotted(data: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value
