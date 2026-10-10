"""Load exporter configuration from YAML (with ${ENV} expansion) or environment."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

from .collector import PoolConfig

_POOL_ENV = re.compile(r"^XEN_POOL(\d+)_(URL|USERNAME|PASSWORD|PASSWORD_FILE|NAME|VERIFY_SSL|TIMEOUT)$")
_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value):
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _norm_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url if "://" in url else "https://" + url


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

    # Numbered pools from the environment: XEN_POOL1_URL, XEN_POOL1_PASSWORD, ...
    # (this is how the docker-compose-only deployment is configured).
    numbered: dict[int, dict] = {}
    for key, value in os.environ.items():
        m = _POOL_ENV.match(key)
        if m and value != "":
            numbered.setdefault(int(m.group(1)), {})[m.group(2).lower()] = value
    known = {_norm_url(p.url) for p in cfg.pools}
    for n in sorted(numbered):
        d = numbered[n]
        if "url" not in d:
            continue  # e.g. only XEN_POOL1_PASSWORD set, used by config.yml via ${...}
        if _norm_url(d["url"]) in known:
            continue
        env_defaults = {"username": os.environ.get("XEN_USERNAME", "root"),
                        "verify_ssl": os.environ.get("XEN_VERIFY_SSL"), **defaults}
        cfg.pools.append(_pool_from_dict(d, env_defaults))
        known.add(_norm_url(d["url"]))

    # Legacy quick-start: XEN_URL (comma-separated) sharing one username/password.
    if not cfg.pools and os.environ.get("XEN_URL"):
        for url in (u.strip() for u in os.environ["XEN_URL"].split(",") if u.strip()):
            cfg.pools.append(_pool_from_dict({
                "url": url,
                "username": os.environ.get("XEN_USERNAME", "root"),
                "password": os.environ.get("XEN_PASSWORD", ""),
                "verify_ssl": os.environ.get("XEN_VERIFY_SSL"),
            }, {}))

    for p in cfg.pools:
        if "POOL-MASTER-IP" in p.url:
            raise SystemExit("Replace POOL-MASTER-IP in .env (XEN_POOL1_URL) with your pool master's "
                             "management IP or hostname.")

    if not cfg.pools:
        raise SystemExit("No pools configured. Set XEN_POOL1_URL and XEN_POOL1_PASSWORD in .env "
                         "(see .env.example), or mount a config.yml at /config/config.yml.")
    return cfg
