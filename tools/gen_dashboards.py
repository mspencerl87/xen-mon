#!/usr/bin/env python3
"""Generate the Grafana dashboards in grafana/dashboards/ (run after editing)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "grafana" / "dashboards"
# Versions for publishing on grafana.com (datasource chosen at import time)
GCOM = ROOT / "grafana" / "grafana.com"
REPO = "https://github.com/mspencerl87/xen-mon"
DS = {"type": "prometheus", "uid": "prometheus"}


class Board:
    def __init__(self, uid: str, title: str, tags: list[str]):
        self.uid, self.title, self.tags = uid, title, tags
        self.panels: list[dict] = []
        self.vars: list[dict] = []
        self._id = 0
        self._x = 0
        self._y = 0
        self._row_h = 0

    # -- layout ----------------------------------------------------------
    def _pos(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._x, self._y = 0, self._y + self._row_h
            self._row_h = 0
        pos = {"x": self._x, "y": self._y, "w": w, "h": h}
        self._x += w
        self._row_h = max(self._row_h, h)
        return pos

    def row(self, title: str, collapsed: bool = False):
        if self._x:
            self._x, self._y = 0, self._y + self._row_h
        self._id += 1
        self.panels.append({"id": self._id, "type": "row", "title": title, "collapsed": collapsed,
                            "gridPos": {"x": 0, "y": self._y, "w": 24, "h": 1}, "panels": []})
        self._y += 1
        self._row_h = 0

    def _panel(self, kind: str, title: str, targets, w: int, h: int, unit: str = "short",
               desc: str = "", options: dict | None = None, defaults: dict | None = None,
               overrides: list | None = None, links: list | None = None) -> dict:
        self._id += 1
        if isinstance(targets, str):
            targets = [(targets, "")]
        fd = {"unit": unit, **(defaults or {})}
        if links:
            fd["links"] = links
        p = {
            "id": self._id, "type": kind, "title": title, "description": desc, "datasource": DS,
            "gridPos": self._pos(w, h),
            "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": lf,
                         "range": kind not in ("stat", "bargauge", "gauge", "table"),
                         "instant": kind in ("stat", "bargauge", "gauge", "table")}
                        for i, (e, lf) in enumerate(targets)],
            "fieldConfig": {"defaults": fd, "overrides": overrides or []},
            "options": options or {},
        }
        self.panels.append(p)
        return p

    def stat(self, title, expr, w=4, h=4, unit="short", thresholds=None, desc="", color_mode="value",
             decimals=None, mappings=None):
        d = {"color": {"mode": "thresholds"},
             "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}}
        if decimals is not None:
            d["decimals"] = decimals
        if mappings:
            d["mappings"] = mappings
        return self._panel("stat", title, expr, w, h, unit, desc,
                           {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                            "colorMode": color_mode, "graphMode": "none", "textMode": "auto",
                            "justifyMode": "auto", "orientation": "auto"}, d)

    def bars(self, title, targets, w=8, h=8, unit="percentunit", max_=1, thresholds=None, desc="",
             links=None):
        d = {"min": 0, "color": {"mode": "thresholds"},
             "thresholds": {"mode": "absolute", "steps": thresholds or [
                 {"color": "green", "value": None}, {"color": "orange", "value": 0.75},
                 {"color": "red", "value": 0.9}]}}
        if max_ is not None:
            d["max"] = max_
        return self._panel("bargauge", title, targets, w, h, unit, desc,
                           {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                            "orientation": "horizontal", "displayMode": "gradient",
                            "showUnfilled": True, "valueMode": "color", "namePlacement": "left",
                            "sizing": "manual", "minVizHeight": 26, "maxVizHeight": 36,
                            "text": {"titleSize": 14, "valueSize": 18}}, d, links=links)

    def ts(self, title, targets, w=12, h=8, unit="short", stack=False, desc="", min_=0, fill=10,
           max_=None, overrides=None, links=None):
        custom = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
                  "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                  "gradientMode": "opacity", "axisSoftMin": min_}
        d = {"custom": custom, "color": {"mode": "palette-classic"}}
        if max_ is not None:
            d["max"] = max_
        return self._panel("timeseries", title, targets, w, h, unit, desc,
                           {"legend": {"displayMode": "table", "placement": "right",
                                       "calcs": ["mean", "max", "lastNotNull"], "showLegend": True},
                            "tooltip": {"mode": "multi", "sort": "desc"}}, d, overrides, links)

    def table(self, title, targets, w=24, h=8, desc="", transformations=None, overrides=None,
              unit="short", links=None):
        p = self._panel("table", title, targets, w, h, unit, desc,
                        {"showHeader": True, "cellHeight": "sm",
                         "footer": {"show": False, "reducer": ["sum"], "fields": ""}},
                        {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                        overrides, links)
        for t in p["targets"]:
            t["format"] = "table"
        p["transformations"] = transformations or []
        return p

    # -- variables -------------------------------------------------------
    def var(self, name, query, label=None, multi=True, include_all=True, hide=0):
        self.vars.append({
            "name": name, "label": label or name, "type": "query", "datasource": DS,
            "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
            "definition": query, "refresh": 2, "sort": 1, "multi": multi, "includeAll": include_all,
            "allValue": ".*" if include_all else None, "hide": hide,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]} if include_all else {},
        })

    def json(self) -> dict:
        return {
            "uid": self.uid, "title": self.title, "tags": self.tags, "editable": True,
            "schemaVersion": 39, "version": 1, "graphTooltip": 1, "refresh": "30s",
            "time": {"from": "now-6h", "to": "now"}, "timezone": "browser",
            "templating": {"list": self.vars}, "annotations": {"list": []},
            "description": "XCP-ng / XenServer monitoring by xen-mon - " + REPO,
            "links": [{"title": "XCP-ng", "type": "dashboards", "tags": ["xen-mon"], "asDropdown": True,
                       "includeVars": False, "keepTime": True},
                      {"title": "xen-mon on GitHub", "type": "link", "url": REPO, "icon": "info",
                       "tooltip": "Docs, issues and updates", "targetBlank": True}],
            "panels": self.panels,
        }


PCT = [{"color": "green", "value": None}, {"color": "orange", "value": 0.75}, {"color": "red", "value": 0.9}]
HOST_LINK = [{"title": "Host details", "url": "/d/xen-host?var-pool=${__field.labels.pool}&var-host=${__field.labels.host}&${__url_time_range}"}]
VM_LINK = [{"title": "VM details", "url": "/d/xen-vm?var-pool=${__field.labels.pool}&var-vm=${__field.labels.vm}&${__url_time_range}"}]
VMS = 'is_dom0="false", pool=~"$pool"'


def overview() -> Board:
    b = Board("xen-overview", "XCP-ng Overview", ["xen-mon", "xcp-ng"])
    b.var("pool", "label_values(xen_pool_info, pool)", "Pool")

    b.row("Summary")
    b.stat("Pools reachable", 'sum(xen_up{pool=~"$pool"}) or vector(0)', w=3,
           thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}])
    b.stat("Pools down", 'count(xen_up{pool=~"$pool"} == 0) or vector(0)', w=3,
           thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
    b.stat("Hosts live", 'sum(xen_host_live{pool=~"$pool"})', w=3)
    b.stat("Hosts not live", 'count(xen_host_live{pool=~"$pool"} == 0) or vector(0)', w=3,
           thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
    b.stat("Running VMs", f'sum(xen_vm_running{{{VMS}}})', w=3)
    b.stat("Halted VMs", f'count(xen_vm_running{{{VMS}}} == 0) or vector(0)', w=3,
           thresholds=[{"color": "text", "value": None}])
    b.stat("Pool CPU", 'avg(xen_host_cpu_avg{pool=~"$pool"})', w=3, unit="percentunit",
           thresholds=PCT, decimals=1)
    b.stat("Pool memory used",
           '1 - sum(xen_host_memory_free_bytes{pool=~"$pool"}) / sum(xen_host_memory_total_bytes{pool=~"$pool"})',
           w=3, unit="percentunit", thresholds=PCT, decimals=1)

    b.row("Hosts")
    b.bars("Host CPU", [('xen_host_cpu_avg{pool=~"$pool"}', "{{host}}")], w=8, links=HOST_LINK)
    b.bars("Host memory used", [(
        '1 - xen_host_memory_free_bytes{pool=~"$pool"} / xen_host_memory_total_bytes{pool=~"$pool"}',
        "{{host}}")], w=8, links=HOST_LINK)
    b.bars("Running VMs per host",
           [(f'count by (pool, host) (xen_vm_running{{{VMS}}} == 1)', "{{host}}")], w=8,
           unit="short", max_=None, thresholds=[{"color": "blue", "value": None}], links=HOST_LINK)
    b.ts("Host CPU usage", [('xen_host_cpu_avg{pool=~"$pool"}', "{{host}}")], unit="percentunit",
         max_=1, links=HOST_LINK)
    b.ts("Host network (rx + tx)", [(
        'sum by (pool, host) (xen_host_pif_rx_bytes{pool=~"$pool", pif!="aggr"} + xen_host_pif_tx_bytes{pool=~"$pool", pif!="aggr"})',
        "{{host}}")], unit="Bps", links=HOST_LINK)

    b.row("Storage")
    b.bars("SR usage", [(
        'xen_sr_used_bytes{pool=~"$pool", content_type!~"iso|disk"} / (xen_sr_size_bytes{pool=~"$pool", content_type!~"iso|disk"} > 0)',
        "{{sr}}")], w=12, h=9)
    b.table("Storage repositories", [
        ('xen_sr_size_bytes{pool=~"$pool", content_type!~"iso|disk"}', ""),
        ('xen_sr_used_bytes{pool=~"$pool", content_type!~"iso|disk"}', ""),
        ('xen_sr_allocated_bytes{pool=~"$pool", content_type!~"iso|disk"}', ""),
    ], w=12, h=9, unit="bytes", transformations=[
        {"id": "joinByField", "options": {"byField": "sr_uuid", "mode": "outer"}},
        {"id": "organize", "options": {
            "excludeByName": {k: True for k in [
                "Time", "Time 1", "Time 2", "Time 3", "__name__", "__name__ 1", "__name__ 2", "__name__ 3",
                "instance", "instance 1", "instance 2", "instance 3", "job", "job 1", "job 2", "job 3",
                "pool 2", "pool 3", "sr 2", "sr 3", "type 2", "type 3", "shared 2", "shared 3",
                "content_type", "content_type 1", "content_type 2", "content_type 3", "sr_uuid"]},
            "renameByName": {"pool 1": "Pool", "sr 1": "SR", "type 1": "Type", "shared 1": "Shared",
                             "Value #A": "Size", "Value #B": "Used", "Value #C": "Allocated"},
            "indexByName": {"pool 1": 0, "sr 1": 1, "type 1": 2, "shared 1": 3,
                            "Value #A": 4, "Value #B": 5, "Value #C": 6}}},
    ])
    b.ts("SR latency (worst host)", [('max by (pool, sr) (xen_host_sr_latency{pool=~"$pool"})', "{{sr}}")],
         unit="ms", w=8)
    b.ts("SR IOPS (all hosts)", [(
        'sum by (pool, sr) (xen_host_sr_iops_read{pool=~"$pool"} + xen_host_sr_iops_write{pool=~"$pool"})',
        "{{sr}}")], unit="iops", w=8)
    b.ts("SR throughput (all hosts)", [(
        'sum by (pool, sr) (xen_host_sr_io_throughput_read{pool=~"$pool"} + xen_host_sr_io_throughput_write{pool=~"$pool"})',
        "{{sr}}")], unit="MiBs", w=8)

    b.row("Top VMs")
    b.ts("Top 10 VMs by CPU", [(
        f'topk(10, avg by (pool, vm) (xen_vm_vcpu_usage{{{VMS}}}))', "{{vm}}")],
        unit="percentunit", w=12, links=VM_LINK)
    b.ts("Top 10 VMs by memory used", [(
        f'topk(10, xen_vm_memory{{{VMS}}} - xen_vm_memory_internal_free{{{VMS}}} * 1024)', "{{vm}}")],
        unit="bytes", w=12, links=VM_LINK)
    b.ts("Top 10 VMs by network", [(
        f'topk(10, sum by (pool, vm) (xen_vm_vif_rx_bytes{{{VMS}}} + xen_vm_vif_tx_bytes{{{VMS}}}))',
        "{{vm}}")], unit="Bps", w=12, links=VM_LINK)
    b.ts("Top 10 VMs by disk throughput", [(
        f'topk(10, sum by (pool, vm) (xen_vm_vbd_read_bytes{{{VMS}}} + xen_vm_vbd_write_bytes{{{VMS}}}))',
        "{{vm}}")], unit="Bps", w=12, links=VM_LINK)

    b.row("Exporter", collapsed=False)
    b.ts("Poll duration", [('xen_poll_duration_seconds{pool=~"$pool"}', "{{pool}}")], unit="s", w=12)
    b.ts("Per-host RRD fetch", [('xen_host_rrd_duration_seconds{pool=~"$pool"}', "{{host}}")],
         unit="s", w=12)
    return b


def host() -> Board:
    b = Board("xen-host", "XCP-ng Host", ["xen-mon", "xcp-ng"])
    b.var("pool", "label_values(xen_pool_info, pool)", "Pool", multi=False, include_all=False)
    b.var("host", 'label_values(xen_host_info{pool="$pool"}, host)', "Host", multi=False, include_all=False)
    H = 'pool="$pool", host="$host"'

    b.row("Status")
    up_map = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"},
                                            "1": {"text": "UP", "color": "green"}}}]
    b.stat("Live", f"xen_host_live{{{H}}}", w=3, mappings=up_map, color_mode="background")
    b.stat("Enabled", f"xen_host_enabled{{{H}}}", w=3, color_mode="background",
           mappings=[{"type": "value", "options": {"0": {"text": "Maintenance", "color": "orange"},
                                                   "1": {"text": "Enabled", "color": "green"}}}])
    b.stat("Role", f"xen_host_is_master{{{H}}}", w=3, mappings=[
        {"type": "value", "options": {"0": {"text": "Member", "color": "blue"},
                                      "1": {"text": "Master", "color": "purple"}}}])
    b.stat("CPU", f"xen_host_cpu_avg{{{H}}}", w=3, unit="percentunit", thresholds=PCT, decimals=1)
    b.stat("Memory used", f"1 - xen_host_memory_free_bytes{{{H}}} / xen_host_memory_total_bytes{{{H}}}",
           w=3, unit="percentunit", thresholds=PCT, decimals=1)
    b.stat("Load avg", f"xen_host_loadavg{{{H}}}", w=3, decimals=2)
    b.stat("Running VMs", f'count(xen_vm_running{{{H}, is_dom0="false"}} == 1) or vector(0)', w=3)
    b.stat("pCPUs", f"xen_host_cpu_count{{{H}}}", w=3)
    b.stat("Performance data", f"xen_host_rrd_up{{{H}}}", w=4, h=3, color_mode="background",
           desc="Whether the exporter can read this host's rrd_updates (CPU, load, network, disk). "
                "If FAILING, check `docker compose logs exporter`.",
           mappings=[{"type": "value", "options": {"0": {"text": "FAILING", "color": "red"},
                                                   "1": {"text": "OK", "color": "green"}}}])
    b.table("Host info", [(f"xen_host_info{{{H}}}", "")], w=20, h=3, transformations=[
        {"id": "organize", "options": {
            "excludeByName": {"Time": True, "Value": True, "__name__": True, "instance": True,
                              "job": True, "pool": True},
            "renameByName": {"host": "Host", "host_uuid": "UUID", "address": "Address",
                             "product_brand": "Product", "product_version": "Version",
                             "xen_version": "Xen", "cpu_model": "CPU"}}}])

    b.row("CPU & memory")
    b.ts("CPU usage per core", [(f"xen_host_cpu_usage{{{H}}}", "cpu{{cpu}}")], unit="percentunit",
         max_=1, fill=0)
    b.ts("Load average", [(f"xen_host_loadavg{{{H}}}", "load")])
    b.ts("Memory", [
        (f"xen_host_memory_total_bytes{{{H}}} - xen_host_memory_free_bytes{{{H}}}", "used"),
        (f"xen_host_memory_total_bytes{{{H}}}", "total"),
    ], unit="bytes", overrides=[{"matcher": {"id": "byName", "options": "total"},
                                 "properties": [{"id": "custom.fillOpacity", "value": 0},
                                                {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}]}])
    b.ts("dom0 memory", [
        (f'xen_vm_memory{{{H}, is_dom0="true"}} - xen_vm_memory_internal_free{{{H}, is_dom0="true"}} * 1024', "used"),
        (f'xen_vm_memory{{{H}, is_dom0="true"}}', "allocated"),
    ], unit="bytes")

    b.row("Network")
    b.ts("PIF receive", [(f'xen_host_pif_rx_bytes{{{H}, pif!="aggr"}}', "{{pif}}")], unit="Bps")
    b.ts("PIF transmit", [(f'xen_host_pif_tx_bytes{{{H}, pif!="aggr"}}', "{{pif}}")], unit="Bps")

    b.row("Storage (as seen by this host)")
    b.ts("SR throughput read", [(f"xen_host_sr_io_throughput_read{{{H}}}", "{{sr}}")], unit="MiBs", w=8)
    b.ts("SR throughput write", [(f"xen_host_sr_io_throughput_write{{{H}}}", "{{sr}}")], unit="MiBs", w=8)
    b.ts("SR latency", [(f"xen_host_sr_latency{{{H}}}", "{{sr}}")], unit="ms", w=8)
    b.ts("SR IOPS read", [(f"xen_host_sr_iops_read{{{H}}}", "{{sr}}")], unit="iops", w=8)
    b.ts("SR IOPS write", [(f"xen_host_sr_iops_write{{{H}}}", "{{sr}}")], unit="iops", w=8)
    b.ts("SR IO wait", [(f"xen_host_sr_iowait{{{H}}}", "{{sr}}")], w=8)

    b.row("VMs on this host")
    b.ts("VM CPU", [(f'avg by (vm) (xen_vm_vcpu_usage{{{H}, is_dom0="false"}})', "{{vm}}")],
         unit="percentunit", links=VM_LINK)
    b.ts("VM network (rx + tx)", [(
        f'sum by (vm) (xen_vm_vif_rx_bytes{{{H}, is_dom0="false"}} + xen_vm_vif_tx_bytes{{{H}, is_dom0="false"}})',
        "{{vm}}")], unit="Bps", links=VM_LINK)
    return b


def vm() -> Board:
    b = Board("xen-vm", "XCP-ng VM", ["xen-mon", "xcp-ng"])
    b.var("pool", "label_values(xen_pool_info, pool)", "Pool", multi=False, include_all=False)
    b.var("vm", 'label_values(xen_vm_info{pool="$pool"}, vm)', "VM", multi=False, include_all=False)
    V = 'pool="$pool", vm="$vm"'

    b.row("Status")
    b.stat("Power state", f"xen_vm_running{{{V}}}", w=4, color_mode="background", mappings=[
        {"type": "value", "options": {"0": {"text": "Halted", "color": "red"},
                                      "1": {"text": "Running", "color": "green"}}}])
    b.stat("CPU", f"avg(xen_vm_vcpu_usage{{{V}}})", w=4, unit="percentunit", thresholds=PCT, decimals=1)
    b.stat("Memory used", f"1 - xen_vm_memory_internal_free{{{V}}} * 1024 / xen_vm_memory{{{V}}}", w=4,
           unit="percentunit", thresholds=PCT, decimals=1,
           desc="Requires guest tools (management agent) in the VM.")
    b.stat("vCPUs", f"xen_vm_vcpus{{{V}}}", w=4)
    b.stat("Memory", f"xen_vm_memory_dynamic_max_bytes{{{V}}}", w=4, unit="bytes")
    b.table("Placement", [(f"xen_vm_info{{{V}}}", "")], w=4, h=4, transformations=[
        {"id": "organize", "options": {"excludeByName": {
            "Time": True, "Value": True, "__name__": True, "instance": True, "job": True, "pool": True,
            "vm": True, "vm_uuid": True, "is_dom0": True, "power_state": True},
            "renameByName": {"host": "Host"}}}])

    b.row("CPU & memory")
    b.ts("vCPU usage", [(f"xen_vm_vcpu_usage{{{V}}}", "vcpu{{vcpu}}"),
                        (f"avg(xen_vm_vcpu_usage{{{V}}})", "average")], unit="percentunit", fill=0)
    b.ts("Memory", [
        (f"xen_vm_memory{{{V}}} - xen_vm_memory_internal_free{{{V}}} * 1024", "used (guest)"),
        (f"xen_vm_memory{{{V}}}", "allocated"),
    ], unit="bytes")

    b.row("Network")
    b.ts("Receive", [(f"xen_vm_vif_rx_bytes{{{V}}}", "vif{{vif}}")], unit="Bps")
    b.ts("Transmit", [(f"xen_vm_vif_tx_bytes{{{V}}}", "vif{{vif}}")], unit="Bps")

    b.row("Disks")
    b.ts("Disk read", [(f"xen_vm_vbd_read_bytes{{{V}}}", "{{device}}")], unit="Bps", w=8)
    b.ts("Disk write", [(f"xen_vm_vbd_write_bytes{{{V}}}", "{{device}}")], unit="Bps", w=8)
    b.ts("Disk IOPS", [(f"xen_vm_vbd_iops_total{{{V}}}", "{{device}}")], unit="iops", w=8)
    b.ts("Disk latency", [(f"xen_vm_vbd_read_latency{{{V}}}", "{{device}} read"),
                          (f"xen_vm_vbd_write_latency{{{V}}}", "{{device}} write")], unit="µs", w=24, fill=0)
    return b


def for_grafana_com(d: dict) -> dict:
    """Same dashboard, but asks for a Prometheus datasource on import."""
    text = json.dumps(d).replace('"uid": "prometheus"', '"uid": "${DS_PROMETHEUS}"')
    out = json.loads(text)
    out.pop("id", None)
    return {
        "__inputs": [{"name": "DS_PROMETHEUS", "label": "Prometheus", "type": "datasource",
                      "pluginId": "prometheus", "pluginName": "Prometheus",
                      "description": "Prometheus that scrapes the xen-mon exporter"}],
        "__requires": [
            {"type": "grafana", "id": "grafana", "name": "Grafana", "version": "10.0.0"},
            {"type": "datasource", "id": "prometheus", "name": "Prometheus", "version": "1.0.0"},
            {"type": "panel", "id": "stat", "name": "Stat", "version": ""},
            {"type": "panel", "id": "bargauge", "name": "Bar gauge", "version": ""},
            {"type": "panel", "id": "timeseries", "name": "Time series", "version": ""},
            {"type": "panel", "id": "table", "name": "Table", "version": ""},
        ],
        **out,
    }


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    GCOM.mkdir(parents=True, exist_ok=True)
    for board in (overview(), host(), vm()):
        d = board.json()
        path = OUT / f"{board.uid}.json"
        path.write_text(json.dumps(d, indent=2) + "\n")
        (GCOM / f"{board.uid}.json").write_text(json.dumps(for_grafana_com(d), indent=2) + "\n")
        print(f"wrote {path.relative_to(ROOT)} + grafana.com copy ({len(board.panels)} panels)")
