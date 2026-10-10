"""Load exporter configuration from YAML (with ${ENV} expansion) or environment."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

from .collector import PoolConfig

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _bool(v, default=False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    pools: list[PoolConfig] = field(default_factory=list)
    interval: float = 30.0
    listen: str = "0.0.0.0"
    port: int = 9890


def _pool_from_dict(d: dict, defaults: dict) -> PoolConfig:
    merged = {**defaults, **d}
    password = merged.get("password")
    if not password and merged.get("password_file"):
        with open(merged["password_file"], encoding="utf-8") as fh:
            password = fh.read().strip()
    if not merged.get("url"):
        raise ValueError(f"pool entry is missing 'url': {d}")
    return PoolConfig(
        url=str(merged["url"]),
        username=str(merged.get("username", "root")),
        password=str(password or ""),
        name=merged.get("name"),
        verify_ssl=_bool(merged.get("verify_ssl"), False),
        timeout=float(merged.get("timeout", 20)),
        host_overrides={str(k): str(v) for k, v in (merged.get("host_overrides") or {}).items()},
    )


def load(path: str | None) -> Config:
    cfg = Config()
    data: dict = {}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = _expand(yaml.safe_load(fh) or {})

    cfg.interval = float(os.environ.get("XEN_INTERVAL", data.get("interval", 30)))
    cfg.listen = os.environ.get("XEN_LISTEN", data.get("listen", "0.0.0.0"))
    cfg.port = int(os.environ.get("XEN_PORT", data.get("port", 9890)))

    defaults = data.get("defaults") or {}
    cfg.pools = [_pool_from_dict(p, defaults) for p in (data.get("pools") or [])]

    # Quick-start: a single pool purely from environment variables.
    if not cfg.pools and os.environ.get("XEN_URL"):
        for i, url in enumerate(u.strip() for u in os.environ["XEN_URL"].split(",") if u.strip()):
            cfg.pools.append(_pool_from_dict({
                "url": url,
                "username": os.environ.get("XEN_USERNAME", "root"),
                "password": os.environ.get("XEN_PASSWORD", ""),
                "verify_ssl": os.environ.get("XEN_VERIFY_SSL"),
            }, {}))

    if not cfg.pools:
        raise SystemExit("No pools configured. Create config/config.yml (see config/config.example.yml) "
                         "or set XEN_URL / XEN_USERNAME / XEN_PASSWORD.")
    return cfg
