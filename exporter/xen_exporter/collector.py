"""Poll XCP-ng pools and expose the results as Prometheus metrics."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from .rrd import map_metric, parse_rrd_updates
from .xapi import XapiError, XapiSession

log = logging.getLogger(__name__)

PREFIX = "xen_"
VM_FILTER = 'field "is_a_template" = "false" and field "is_a_snapshot" = "false"'

Sample = tuple[str, dict[str, str], float]


@dataclass
class PoolConfig:
    url: str
    username: str
    password: str
    name: str | None = None
    verify_ssl: bool = False
    timeout: float = 20.0
    host_overrides: dict[str, str] = field(default_factory=dict)


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class PoolPoller:
    def __init__(self, cfg: PoolConfig, rrd_workers: int = 8):
        self.cfg = cfg
        self.session = XapiSession(cfg.url, cfg.username, cfg.password,
                                   cfg.verify_ssl, cfg.timeout)
        self.rrd_workers = rrd_workers
        self.label = cfg.name or cfg.url

    # ------------------------------------------------------------------
    def _vms(self) -> dict:
        try:
            return self.session.call("VM.get_all_records_where", VM_FILTER)
        except XapiError as e:
            if e.code != "MESSAGE_METHOD_UNKNOWN":
                raise
            return {k: v for k, v in self.session.call("VM.get_all_records").items()
                    if not v.get("is_a_template") and not v.get("is_a_snapshot")}

    def poll(self) -> list[Sample]:
        s = self.session
        pools = s.call("pool.get_all_records")
        pool_ref, pool_rec = next(iter(pools.items()))
        pool_name = self.cfg.name or pool_rec.get("name_label") or self.cfg.url
        self.label = pool_name

        hosts = s.call("host.get_all_records")
        host_metrics = s.call("host_metrics.get_all_records")
        vms = self._vms()
        srs = s.call("SR.get_all_records")

        out: list[Sample] = []
        P = {"pool": pool_name}

        master_name = hosts.get(pool_rec.get("master"), {}).get("name_label", "")
        out.append(("pool_info", {**P, "pool_uuid": pool_rec.get("uuid", ""),
                                  "master": master_name}, 1))

        # ---- hosts -----------------------------------------------------
        host_by_uuid: dict[str, str] = {}
        host_name_by_ref: dict[str, str] = {}
        for ref, h in hosts.items():
            name = h.get("name_label", ref)
            host_by_uuid[h["uuid"]] = name
            host_name_by_ref[ref] = name
            hl = {**P, "host": name, "host_uuid": h["uuid"]}
            sv = h.get("software_version", {}) or {}
            out.append(("host_info", {**hl, "address": h.get("address", ""),
                                      "product_brand": sv.get("product_brand", ""),
                                      "product_version": sv.get("product_version", ""),
                                      "xen_version": sv.get("xen", ""),
                                      "cpu_model": (h.get("cpu_info") or {}).get("modelname", "")}, 1))
            m = host_metrics.get(h.get("metrics"), {})
            out.append(("host_live", hl, 1 if m.get("live") else 0))
            out.append(("host_enabled", hl, 1 if h.get("enabled") else 0))
            out.append(("host_is_master", hl, 1 if ref == pool_rec.get("master") else 0))
            out.append(("host_memory_total_bytes", hl, _num(m.get("memory_total"))))
            out.append(("host_memory_free_bytes", hl, _num(m.get("memory_free"))))
            out.append(("host_cpu_count", hl, len(h.get("host_CPUs", []))))

        # ---- VMs -------------------------------------------------------
        vm_by_uuid: dict[str, tuple[str, str, bool]] = {}
        for ref, v in vms.items():
            host = host_name_by_ref.get(v.get("resident_on"), "")
            dom0 = bool(v.get("is_control_domain"))
            name = v.get("name_label", ref)
            if dom0:
                name = f"dom0 ({host})" if host else name
            vm_by_uuid[v["uuid"]] = (name, host, dom0)
            vl = {**P, "vm": name, "vm_uuid": v["uuid"], "host": host,
                  "is_dom0": str(dom0).lower()}
            out.append(("vm_info", {**vl, "power_state": v.get("power_state", "")}, 1))
            out.append(("vm_running", vl, 1 if v.get("power_state") == "Running" else 0))
            out.append(("vm_vcpus", vl, _num(v.get("VCPUs_at_startup"))))
            out.append(("vm_memory_dynamic_max_bytes", vl, _num(v.get("memory_dynamic_max"))))

        # ---- SRs -------------------------------------------------------
        sr_by_short: dict[str, tuple[str, str]] = {}
        for ref, sr in srs.items():
            sr_by_short[sr["uuid"][:8]] = (sr.get("name_label", ref), sr["uuid"])
            sl = {**P, "sr": sr.get("name_label", ref), "sr_uuid": sr["uuid"],
                  "type": sr.get("type", ""), "content_type": sr.get("content_type", ""),
                  "shared": str(bool(sr.get("shared"))).lower()}
            out.append(("sr_size_bytes", sl, _num(sr.get("physical_size"))))
            out.append(("sr_used_bytes", sl, _num(sr.get("physical_utilisation"))))
            out.append(("sr_allocated_bytes", sl, _num(sr.get("virtual_allocation"))))

        # ---- RRD (per host, in parallel) -------------------------------
        def fetch(ref_host):
            ref, h = ref_host
            name = h.get("name_label", ref)
            addr = (self.cfg.host_overrides.get(name)
                    or self.cfg.host_overrides.get(h["uuid"])
                    or h.get("address"))
            t0 = time.monotonic()
            try:
                return name, h["uuid"], parse_rrd_updates(s.rrd_updates(addr)), time.monotonic() - t0
            except Exception as e:  # noqa: BLE001
                log.warning("[%s] rrd_updates from %s (%s) failed: %s", pool_name, name, addr, e)
                return name, h["uuid"], None, time.monotonic() - t0

        live_hosts = [(r, h) for r, h in hosts.items()
                      if host_metrics.get(h.get("metrics"), {}).get("live", True)]
        seen: set[tuple[str, str, str]] = set()
        with ThreadPoolExecutor(max_workers=min(self.rrd_workers, max(1, len(live_hosts)))) as ex:
            for hname, huuid, samples, dur in ex.map(fetch, live_hosts):
                hl = {**P, "host": hname, "host_uuid": huuid}
                out.append(("host_rrd_up", hl, 0 if samples is None else 1))
                out.append(("host_rrd_duration_seconds", hl, dur))
                for smp in samples or []:
                    key = (smp.obj_type, smp.obj_uuid, smp.name)
                    if key in seen:  # e.g. VM mid-migration reported by two hosts
                        continue
                    seen.add(key)
                    mm = map_metric(smp.obj_type, smp.name)
                    if smp.obj_type == "host":
                        labels = {**P, "host": host_by_uuid.get(smp.obj_uuid, smp.obj_uuid),
                                  "host_uuid": smp.obj_uuid, **mm.labels}
                        if "sr_short" in mm.labels:
                            sr_name, sr_uuid = sr_by_short.get(mm.labels["sr_short"], ("", ""))
                            labels.update(sr=sr_name, sr_uuid=sr_uuid)
                    elif smp.obj_type == "vm":
                        vname, vhost, dom0 = vm_by_uuid.get(smp.obj_uuid, (smp.obj_uuid, hname, False))
                        labels = {**P, "vm": vname, "vm_uuid": smp.obj_uuid, "host": vhost or hname,
                                  "is_dom0": str(dom0).lower(), **mm.labels}
                    else:
                        labels = {**P, "uuid": smp.obj_uuid, **mm.labels}
                    out.append((mm.name, labels, smp.value))
        return out


class PoolManager(Collector):
    """Runs one polling thread per pool and serves the latest snapshot."""

    def __init__(self, pools: list[PoolConfig], interval: float = 30.0):
        self.pollers = [PoolPoller(p) for p in pools]
        self.interval = interval
        self._lock = threading.Lock()
        self._snapshots: dict[int, list[Sample]] = {}
        self._status: dict[int, tuple[str, int, float, float]] = {}
        self._stop = threading.Event()

    def start(self) -> None:
        for i, p in enumerate(self.pollers):
            t = threading.Thread(target=self._loop, args=(i, p), daemon=True,
                                 name=f"poll-{p.cfg.name or p.cfg.url}")
            t.start()

    def stop(self) -> None:
        self._stop.set()
        for p in self.pollers:
            p.session.logout()

    def poll_once(self, idx: int) -> None:
        p = self.pollers[idx]
        t0 = time.monotonic()
        try:
            samples = p.poll()
            up = 1
        except Exception as e:  # noqa: BLE001
            log.error("[%s] poll failed: %s", p.label, e)
            samples, up = [], 0
            p.session.session_id = None  # force a fresh login next time
        dur = time.monotonic() - t0
        with self._lock:
            self._snapshots[idx] = samples
            self._status[idx] = (p.label, up, dur, time.time())
        log.info("[%s] polled %d samples in %.2fs (up=%d)", p.label, len(samples), dur, up)

    def _loop(self, idx: int, p: PoolPoller) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.poll_once(idx)
            self._stop.wait(max(1.0, self.interval - (time.monotonic() - started)))

    # ------------------------------------------------------------------
    def collect(self):
        with self._lock:
            snaps = [s for s in self._snapshots.values()]
            status = list(self._status.values())

        up = GaugeMetricFamily(PREFIX + "up", "1 if the last poll of the pool succeeded", labels=["pool"])
        dur = GaugeMetricFamily(PREFIX + "poll_duration_seconds", "Duration of the last pool poll",
                                labels=["pool"])
        ts = GaugeMetricFamily(PREFIX + "poll_timestamp_seconds", "Unix time of the last pool poll",
                               labels=["pool"])
        for label, u, d, t in status:
            up.add_metric([label], u)
            dur.add_metric([label], d)
            ts.add_metric([label], t)
        yield up
        yield dur
        yield ts

        # Group by metric name; union label names so every series in a family matches.
        grouped: dict[str, list[tuple[dict[str, str], float]]] = {}
        for snap in snaps:
            for name, labels, value in snap:
                grouped.setdefault(name, []).append((labels, value))
        for name, items in sorted(grouped.items()):
            keys: list[str] = []
            for labels, _ in items:
                for k in labels:
                    if k not in keys:
                        keys.append(k)
            fam = GaugeMetricFamily(PREFIX + name, f"XCP-ng metric {name}", labels=keys)
            dedupe: set[tuple[str, ...]] = set()
            for labels, value in items:
                lv = tuple(str(labels.get(k, "")) for k in keys)
                if lv in dedupe:
                    continue
                dedupe.add(lv)
                fam.add_metric(list(lv), value)
            yield fam
