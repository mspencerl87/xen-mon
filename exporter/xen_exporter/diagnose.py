"""Connectivity check: python -m xen_exporter.diagnose  (or: docker compose exec exporter ...)

For every configured pool, logs in, checks clock skew, and fetches rrd_updates
from each host, printing what came back so problems are easy to spot.
"""

from __future__ import annotations

import os
import sys
import time

from .config import load
from .rrd import parse_rrd_updates
from .xapi import XapiSession


def _ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def _bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def main() -> int:
    cfg = load(os.environ.get("XEN_CONFIG", "/config/config.yml"))
    failures = 0
    for p in cfg.pools:
        print(f"\n== {p.name or p.url} ==")
        s = XapiSession(p.url, p.username, p.password, p.verify_ssl, p.timeout)
        try:
            s.login()
            _ok(f"logged in to {s.url} as {p.username}")
        except Exception as e:  # noqa: BLE001
            _bad(f"login to {p.url} failed: {e}")
            failures += 1
            continue
        pool_ref, pool = next(iter(s.call("pool.get_all_records").items()))
        hosts = s.call("host.get_all_records")
        print(f"         pool name: {pool.get('name_label') or '(unnamed)'}  hosts: {len(hosts)}")

        st = s.server_time(pool.get("master"))
        offset = 0.0 if st is None else st - time.time()
        if st is None:
            print("  [WARN] could not read master's clock")
        elif abs(offset) > 30:
            print(f"  [WARN] clock skew {offset:+.0f}s vs master (compensated, but fix NTP)")
        else:
            _ok(f"clock skew {offset:+.1f}s")

        for ref, h in hosts.items():
            name = h.get("name_label", ref)
            addr = p.host_overrides.get(name) or p.host_overrides.get(h["uuid"]) or h.get("address")
            t0 = time.monotonic()
            try:
                body = s.rrd_updates(addr, clock_offset=offset)
            except Exception as e:  # noqa: BLE001
                _bad(f"{name} ({addr}): rrd_updates request failed: {e}")
                failures += 1
                continue
            dt = time.monotonic() - t0
            try:
                samples = parse_rrd_updates(body)
            except Exception as e:  # noqa: BLE001
                _bad(f"{name} ({addr}): could not parse response ({e}); starts with {body[:200]!r}")
                failures += 1
                continue
            if not samples:
                _bad(f"{name} ({addr}): response had no values; starts with {body[:300]!r}")
                failures += 1
                continue
            hs = sorted({x.name for x in samples if x.obj_type == "host"})
            vms = {x.obj_uuid for x in samples if x.obj_type == "vm"}
            _ok(f"{name} ({addr}): {len(samples)} values in {dt:.2f}s, "
                f"{len(hs)} host metrics, {len(vms)} VMs")
            print(f"         e.g. {', '.join(hs[:8])}")
    print("\nAll checks passed." if not failures else f"\n{failures} problem(s) found.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
