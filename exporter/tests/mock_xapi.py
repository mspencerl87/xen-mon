"""A tiny fake XAPI pool used by the tests (and handy for local development).

Serves XML-RPC on POST / and rrd_updates XML on GET /rrd_updates.
Hosts are identified by the HTTP Host header, so point several DNS names
(or docker network aliases) at this one server, listed in MOCK_HOSTS.

    cd exporter/tests && MOCK_HOSTS=127.0.0.1,localhost MOCK_PORT=18080 python mock_xapi.py
"""

from __future__ import annotations

import math
import os
import random
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from xmlrpc.client import dumps, loads

GiB = 1024 ** 3
rnd = random.Random(42)


def _u() -> str:
    return str(uuid.UUID(int=rnd.getrandbits(128), version=4))


class FakePool:
    def __init__(self, addresses: list[str], name: str = "demo-pool"):
        self.sessions: set[str] = set()
        self.hosts, self.host_metrics, self.vms, self.srs = {}, {}, {}, {}
        for i, addr in enumerate(addresses):
            ref, mref = f"OpaqueRef:host{i}", f"OpaqueRef:hm{i}"
            self.hosts[ref] = {
                "uuid": _u(), "name_label": f"xcp-host-{i + 1}", "address": addr,
                "enabled": True, "metrics": mref,
                "host_CPUs": [f"OpaqueRef:cpu{i}-{c}" for c in range(16)],
                "software_version": {"product_brand": "XCP-ng", "product_version": "8.3.0",
                                     "xen": "4.17.5"},
                "cpu_info": {"modelname": "AMD EPYC 7302P 16-Core Processor"},
            }
            self.host_metrics[mref] = {"live": True, "memory_total": str(256 * GiB),
                                       "memory_free": str(int((96 + 20 * i) * GiB))}
        self.pool = {"OpaqueRef:pool": {"uuid": _u(), "name_label": name,
                                        "master": "OpaqueRef:host0"}}
        host_refs = list(self.hosts)
        for i, href in enumerate(host_refs):  # one dom0 per host
            self.vms[f"OpaqueRef:dom0-{i}"] = {
                "uuid": _u(), "name_label": f"Control domain on host: xcp-host-{i + 1}",
                "is_control_domain": True, "is_a_template": False, "is_a_snapshot": False,
                "power_state": "Running", "resident_on": href, "VCPUs_at_startup": "8",
                "memory_dynamic_max": str(8 * GiB)}
        names = ["web-01", "web-02", "db-01", "k8s-node-1", "k8s-node-2", "backup-proxy", "dev-sandbox"]
        for i, n in enumerate(names):
            running = n != "dev-sandbox"
            self.vms[f"OpaqueRef:vm{i}"] = {
                "uuid": _u(), "name_label": n, "is_control_domain": False,
                "is_a_template": False, "is_a_snapshot": False,
                "power_state": "Running" if running else "Halted",
                "resident_on": host_refs[i % len(host_refs)] if running else "OpaqueRef:NULL",
                "VCPUs_at_startup": str(rnd.choice([2, 4, 8])),
                "memory_dynamic_max": str(rnd.choice([4, 8, 16]) * GiB)}
        for i, (n, t, size, used, shared) in enumerate([
            ("Local storage xcp-host-1", "ext", 900, 410, False),
            ("NFS shared", "nfs", 4000, 3480, True),
            ("iSCSI fast", "lvmoiscsi", 2000, 900, True),
        ]):
            self.srs[f"OpaqueRef:sr{i}"] = {
                "uuid": _u(), "name_label": n, "type": t, "content_type": "user", "shared": shared,
                "physical_size": str(size * GiB), "physical_utilisation": str(used * GiB),
                "virtual_allocation": str(int(used * 1.4) * GiB)}

    # -- XML-RPC ---------------------------------------------------------
    def dispatch(self, method: str, params: tuple):
        ok = lambda v: {"Status": "Success", "Value": v}  # noqa: E731
        if method == "session.login_with_password":
            if params[1] != os.environ.get("MOCK_PASSWORD", "demo"):
                return {"Status": "Failure", "ErrorDescription": ["SESSION_AUTHENTICATION_FAILED"]}
            sid = "OpaqueRef:" + _u()
            self.sessions.add(sid)
            return ok(sid)
        if method == "session.logout":
            self.sessions.discard(params[0])
            return ok("")
        if not params or params[0] not in self.sessions:
            return {"Status": "Failure", "ErrorDescription": ["SESSION_INVALID", params[0] if params else ""]}
        table = {
            "pool.get_all_records": self.pool,
            "host.get_all_records": self.hosts,
            "host_metrics.get_all_records": self.host_metrics,
            "VM.get_all_records": self.vms,
            "VM.get_all_records_where": {k: v for k, v in self.vms.items()
                                         if not v["is_a_template"] and not v["is_a_snapshot"]},
            "SR.get_all_records": self.srs,
        }
        if method in table:
            return ok(table[method])
        if method == "host.get_servertime":
            from xmlrpc.client import DateTime
            return ok(DateTime(time.gmtime(time.time() + float(os.environ.get("MOCK_SKEW", "0")))))
        return {"Status": "Failure", "ErrorDescription": ["MESSAGE_METHOD_UNKNOWN", method]}

    # -- RRD -------------------------------------------------------------
    @staticmethod
    def _wave(seed: int, t: float, lo: float, hi: float, period: float = 900) -> float:
        x = 0.5 + 0.35 * math.sin(2 * math.pi * (t / period) + seed) + 0.15 * random.random()
        return lo + (hi - lo) * max(0.0, min(1.0, x))

    def rrd_xml(self, host_ref: str, start: int) -> str:
        h = self.hosts[host_ref]
        cols: list[tuple[str, callable]] = []
        hk = f"AVERAGE:host:{h['uuid']}:"
        seed = hash(h["uuid"]) % 100
        for c in range(len(h["host_CPUs"])):
            cols.append((f"{hk}cpu{c}", lambda t, c=c: self._wave(seed + c, t, 0.05, 0.8)))
        cols += [
            (f"{hk}cpu_avg", lambda t: self._wave(seed, t, 0.1, 0.6)),
            (f"{hk}loadavg", lambda t: self._wave(seed, t, 0.5, 6)),
            (f"{hk}memory_total_kib", lambda t: 256 * 1024 * 1024),
            (f"{hk}memory_free_kib", lambda t: self._wave(seed, t, 80, 120, 3600) * 1024 * 1024),
            (f"{hk}xapi_memory_usage_kib", lambda t: 180_000),
            (f"{hk}pif_eth0_rx", lambda t: self._wave(seed, t, 1e6, 80e6)),
            (f"{hk}pif_eth0_tx", lambda t: self._wave(seed + 1, t, 1e6, 60e6)),
            (f"{hk}pif_eth1_rx", lambda t: self._wave(seed + 2, t, 1e5, 2e7)),
            (f"{hk}pif_eth1_tx", lambda t: self._wave(seed + 3, t, 1e5, 2e7)),
        ]
        for sr in self.srs.values():
            s8 = sr["uuid"][:8]
            cols += [
                (f"{hk}io_throughput_read_{s8}", lambda t: self._wave(seed + 4, t, 1, 120)),
                (f"{hk}io_throughput_write_{s8}", lambda t: self._wave(seed + 5, t, 1, 80)),
                (f"{hk}iops_read_{s8}", lambda t: self._wave(seed + 6, t, 20, 3000)),
                (f"{hk}iops_write_{s8}", lambda t: self._wave(seed + 7, t, 20, 2000)),
                (f"{hk}latency_{s8}", lambda t: self._wave(seed + 8, t, 0.2, 12)),
                (f"{hk}iowait_{s8}", lambda t: self._wave(seed + 9, t, 0, 0.3)),
            ]
        for v in self.vms.values():
            if v["resident_on"] != host_ref or v["power_state"] != "Running":
                continue
            vk = f"AVERAGE:vm:{v['uuid']}:"
            vs = hash(v["uuid"]) % 100
            mem = float(v["memory_dynamic_max"])
            for c in range(int(v["VCPUs_at_startup"])):
                cols.append((f"{vk}cpu{c}", lambda t, c=c, vs=vs: self._wave(vs + c, t, 0.01, 0.95)))
            cols += [
                (f"{vk}memory", lambda t, m=mem: m),
                (f"{vk}memory_target", lambda t, m=mem: m),
                (f"{vk}memory_internal_free",
                 lambda t, m=mem, vs=vs: self._wave(vs, t, 0.1, 0.6, 1800) * m / 1024),
                (f"{vk}vif_0_rx", lambda t, vs=vs: self._wave(vs + 1, t, 1e4, 2e7)),
                (f"{vk}vif_0_tx", lambda t, vs=vs: self._wave(vs + 2, t, 1e4, 2e7)),
                (f"{vk}vbd_xvda_read", lambda t, vs=vs: self._wave(vs + 3, t, 0, 5e7)),
                (f"{vk}vbd_xvda_write", lambda t, vs=vs: self._wave(vs + 4, t, 0, 3e7)),
                (f"{vk}vbd_xvda_read_latency", lambda t, vs=vs: self._wave(vs + 5, t, 100, 4000)),
                (f"{vk}vbd_xvda_write_latency", lambda t, vs=vs: self._wave(vs + 6, t, 100, 6000)),
                (f"{vk}vbd_xvda_iops_total", lambda t, vs=vs: self._wave(vs + 7, t, 5, 900)),
            ]
        now = int(time.time() + float(os.environ.get("MOCK_SKEW", "0"))) // 5 * 5
        start = max(start, now - 600)
        times = list(range(now, start - 1, -5))
        legend = "".join(f"<entry>{n}</entry>" for n, _ in cols)
        rows = "".join("<row><t>%d</t>%s</row>" % (t, "".join(f"<v>{f(t):.6E}</v>" for _, f in cols))
                       for t in times)
        return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><xport><meta><start>{start}</start>"
                f"<step>5</step><end>{now}</end><rows>{len(times)}</rows><columns>{len(cols)}</columns>"
                f"<legend>{legend}</legend></meta><data>{rows}</data></xport>")


def make_handler(pool: FakePool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # quiet
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            params, method = loads(body)
            resp = dumps((pool.dispatch(method, params),), methodresponse=True).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path != "/rrd_updates":
                self.send_error(404)
                return
            q = parse_qs(u.query)
            if q.get("session_id", [""])[0] not in pool.sessions:
                self.send_error(401)
                return
            hostname = (self.headers.get("Host") or "").split(":")[0]
            ref = next((r for r, h in pool.hosts.items() if h["address"] == hostname),
                       next(iter(pool.hosts)))
            body = pool.rrd_xml(ref, int(q.get("start", ["0"])[0])).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(port: int, addresses: list[str], name: str = "demo-pool") -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(FakePool(addresses, name)))
    return srv


if __name__ == "__main__":
    addrs = [a.strip() for a in os.environ.get("MOCK_HOSTS", "mock-host-1,mock-host-2").split(",")]
    port = int(os.environ.get("MOCK_PORT", "80"))
    print(f"fake XAPI pool on :{port}, hosts={addrs}", flush=True)
    serve(port, addrs, os.environ.get("MOCK_POOL_NAME", "demo-pool")).serve_forever()
