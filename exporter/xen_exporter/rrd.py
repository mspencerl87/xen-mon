"""Parse XAPI ``rrd_updates`` XML and map raw RRD names to Prometheus metrics."""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class RrdSample:
    """Latest value of one RRD data source."""

    obj_type: str  # "host" | "vm" | "sr"
    obj_uuid: str
    name: str  # raw RRD data-source name, e.g. "cpu0", "vif_0_rx"
    value: float


_BARE_KEY = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:')


def _parse_json(text: str) -> tuple[list[str], list[tuple[float, list]]]:
    # Older XAPI versions emit JSON with unquoted keys; quote them first.
    try:
        doc = json.loads(text)
    except ValueError:
        doc = json.loads(_BARE_KEY.sub(r'\1"\2":', text))
    legend = [str(e) for e in doc["meta"]["legend"]]
    rows = [(float(r.get("t", 0)), list(r.get("values", []))) for r in doc.get("data", [])]
    return legend, rows


def _parse_xml(text: str) -> tuple[list[str], list[tuple[float, list]]]:
    root = ET.fromstring(text)
    legend = [e.text or "" for e in root.findall("./meta/legend/entry")]
    rows = [(float(r.findtext("t", "0")), [v.text for v in r.findall("v")])
            for r in root.findall("./data/row")]
    return legend, rows


def parse_rrd_updates(text: str) -> list[RrdSample]:
    """Return the newest non-NaN value for every column in an rrd_updates document (XML or JSON)."""
    text = text.lstrip("\ufeff \r\n\t")
    legend, rows = _parse_json(text) if text.startswith("{") else _parse_xml(text)
    # Rows are not guaranteed to be ordered; newest first.
    rows.sort(key=lambda r: r[0], reverse=True)

    latest: list[float | None] = [None] * len(legend)
    remaining = len(legend)
    for _t, values in rows:
        if remaining == 0:
            break
        for i, v in enumerate(values):
            if i >= len(legend) or latest[i] is not None:
                continue
            try:
                val = float("nan" if v is None else v)
            except ValueError:
                continue
            if math.isnan(val) or math.isinf(val):
                continue
            latest[i] = val
            remaining -= 1

    out: list[RrdSample] = []
    for entry, val in zip(legend, latest):
        if val is None:
            continue
        # "AVERAGE:host:<uuid>:cpu0"  (name may itself contain ':' in theory)
        parts = entry.split(":", 3)
        if len(parts) != 4:
            continue
        _cf, obj_type, obj_uuid, name = parts
        out.append(RrdSample(obj_type, obj_uuid, name, val))
    return out


_SANITIZE = re.compile(r"[^a-zA-Z0-9_]")


def sanitize(name: str) -> str:
    s = _SANITIZE.sub("_", name).strip("_").lower()
    return re.sub(r"_+", "_", s)


@dataclass
class MappedMetric:
    name: str
    labels: dict[str, str] = field(default_factory=dict)


_SR_STAT = (
    "io_throughput_read|io_throughput_write|io_throughput_total|"
    "iops_read|iops_write|iops_total|iowait|inflight|"
    "read_latency|write_latency|latency|avgqu_sz"
)

# (regex, metric-name template, {label: group-index})
_HOST_RULES: list[tuple[re.Pattern, str, dict[str, int]]] = [
    (re.compile(r"^cpu(\d+)$"), "host_cpu_usage", {"cpu": 1}),
    (re.compile(r"^cpu(\d+)-C(\d+)$"), "host_cpu_cstate", {"cpu": 1, "state": 2}),
    (re.compile(r"^cpu(\d+)-P(\d+)$"), "host_cpu_pstate", {"cpu": 1, "state": 2}),
    (re.compile(r"^CPU(\d+)-avg-freq$"), "host_cpu_avg_freq_mhz", {"cpu": 1}),
    (re.compile(r"^pif_([^_]+)_(rx|tx)$"), "host_pif_{2}_bytes", {"pif": 1}),
    (re.compile(r"^pif_([^_]+)_(rx|tx)_errors$"), "host_pif_{2}_errors", {"pif": 1}),
    (re.compile(rf"^({_SR_STAT})_([0-9a-f]{{8}})$"), "host_sr_{1}", {"sr_short": 2}),
]

_VM_RULES: list[tuple[re.Pattern, str, dict[str, int]]] = [
    (re.compile(r"^cpu(\d+)$"), "vm_vcpu_usage", {"vcpu": 1}),
    (re.compile(r"^vif_(\d+)_(rx|tx)$"), "vm_vif_{2}_bytes", {"vif": 1}),
    (re.compile(r"^vif_(\d+)_(rx|tx)_errors$"), "vm_vif_{2}_errors", {"vif": 1}),
    (re.compile(r"^vbd_([^_]+)_(read|write)$"), "vm_vbd_{2}_bytes", {"device": 1}),
    (re.compile(r"^vbd_([^_]+)_(.+)$"), "vm_vbd_{2}", {"device": 1}),
]


def map_metric(obj_type: str, name: str) -> MappedMetric:
    rules = _HOST_RULES if obj_type == "host" else _VM_RULES if obj_type == "vm" else []
    for rx, template, label_groups in rules:
        m = rx.match(name)
        if not m:
            continue
        metric = template
        for idx in range(1, (m.lastindex or 0) + 1):
            metric = metric.replace("{%d}" % idx, m.group(idx))
        return MappedMetric(sanitize(metric), {k: m.group(g) for k, g in label_groups.items()})
    return MappedMetric(sanitize(f"{obj_type}_{name}"))
