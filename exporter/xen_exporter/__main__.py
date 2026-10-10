"""Entry point: python -m xen_exporter [--config path]"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading

from prometheus_client import REGISTRY, start_http_server

from . import __version__
from .collector import PoolManager
from .config import load


def main() -> None:
    ap = argparse.ArgumentParser(description="Prometheus exporter for XCP-ng / XenServer pools")
    ap.add_argument("--config", default=os.environ.get("XEN_CONFIG", "/config/config.yml"))
    ap.add_argument("--log-level", default=os.environ.get("XEN_LOG_LEVEL", "INFO"))
    args = ap.parse_args()

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("xen_exporter")

    cfg = load(args.config)
    log.info("xen-mon exporter %s: %d pool(s), interval %ss, listening on %s:%d",
             __version__, len(cfg.pools), cfg.interval, cfg.listen, cfg.port)

    mgr = PoolManager(cfg.pools, cfg.interval)
    REGISTRY.register(mgr)
    start_http_server(cfg.port, addr=cfg.listen)
    mgr.start()

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    log.info("shutting down")
    mgr.stop()


if __name__ == "__main__":
    main()
