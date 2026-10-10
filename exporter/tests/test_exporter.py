import threading
import time

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from xen_exporter.collector import PoolConfig, PoolManager
from mock_xapi import serve
from xen_exporter.rrd import map_metric, parse_rrd_updates

XML = """<xport><meta><start>0</start><step>5</step><end>10</end><rows>2</rows><columns>3</columns>
<legend><entry>AVERAGE:host:h1:cpu0</entry><entry>AVERAGE:vm:v1:vbd_xvda_read</entry>
<entry>AVERAGE:vm:v1:memory</entry></legend></meta>
<data><row><t>10</t><v>0.5</v><v>NaN</v><v>1024</v></row>
<row><t>5</t><v>0.1</v><v>42</v><v>2048</v></row></data></xport>"""


def test_parse_takes_newest_non_nan():
    got = {(s.obj_type, s.obj_uuid, s.name): s.value for s in parse_rrd_updates(XML)}
    assert got == {("host", "h1", "cpu0"): 0.5, ("vm", "v1", "vbd_xvda_read"): 42.0,
                   ("vm", "v1", "memory"): 1024.0}


@pytest.mark.parametrize("t,name,metric,labels", [
    ("host", "cpu3", "host_cpu_usage", {"cpu": "3"}),
    ("host", "pif_eth0_rx", "host_pif_rx_bytes", {"pif": "eth0"}),
    ("host", "pif_bond0_tx_errors", "host_pif_tx_errors", {"pif": "bond0"}),
    ("host", "iops_total_a1b2c3d4", "host_sr_iops_total", {"sr_short": "a1b2c3d4"}),
    ("host", "read_latency_a1b2c3d4", "host_sr_read_latency", {"sr_short": "a1b2c3d4"}),
    ("host", "memory_free_kib", "host_memory_free_kib", {}),
    ("host", "cpu2-C1", "host_cpu_cstate", {"cpu": "2", "state": "1"}),
    ("vm", "cpu1", "vm_vcpu_usage", {"vcpu": "1"}),
    ("vm", "vif_2_tx", "vm_vif_tx_bytes", {"vif": "2"}),
    ("vm", "vbd_xvdb_write", "vm_vbd_write_bytes", {"device": "xvdb"}),
    ("vm", "vbd_xvda_read_latency", "vm_vbd_read_latency", {"device": "xvda"}),
    ("vm", "memory_internal_free", "vm_memory_internal_free", {}),
])
def test_map_metric(t, name, metric, labels):
    m = map_metric(t, name)
    assert (m.name, m.labels) == (metric, labels)


@pytest.fixture()
def mock_pool():
    srv = serve(0, ["127.0.0.1", "localhost"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _scrape(mgr):
    reg = CollectorRegistry()
    reg.register(mgr)
    return generate_latest(reg).decode()


def test_end_to_end_against_mock(mock_pool):
    mgr = PoolManager([PoolConfig(url=mock_pool, username="root", password="demo")])
    mgr.poll_once(0)
    text = _scrape(mgr)
    assert 'xen_up{pool="demo-pool"} 1.0' in text
    assert text.count("xen_host_live{") == 2
    assert 'xen_host_rrd_up{host="xcp-host-1"' in text or 'host="xcp-host-1"' in text
    assert "xen_host_cpu_usage{" in text
    assert 'xen_vm_vcpu_usage{' in text and 'vm="web-01"' in text
    assert 'xen_host_sr_iops_read{' in text and 'sr="NFS shared"' in text
    assert 'xen_sr_used_bytes{' in text
    assert 'xen_vm_running{' in text and 'vm="dev-sandbox"' in text
    # both hosts returned rrd data
    assert text.count("xen_host_rrd_up{") == 2 and " 0.0\n" not in "".join(
        l + "\n" for l in text.splitlines() if l.startswith("xen_host_rrd_up"))


def test_bad_password_sets_up_zero(mock_pool):
    mgr = PoolManager([PoolConfig(url=mock_pool, username="root", password="nope", name="p1")])
    mgr.poll_once(0)
    assert 'xen_up{pool="p1"} 0.0' in _scrape(mgr)


def test_session_expiry_relogin(mock_pool):
    mgr = PoolManager([PoolConfig(url=mock_pool, username="root", password="demo")])
    mgr.poll_once(0)
    mgr.pollers[0].session.session_id = "OpaqueRef:stale"
    mgr.poll_once(0)
    assert 'xen_up{pool="demo-pool"} 1.0' in _scrape(mgr)


def test_parse_json_with_bare_keys():
    doc = ('{meta: {start: 0, step: 5, end: 10, rows: 1, columns: 2, '
           'legend: ["AVERAGE:host:h1:cpu_avg", "AVERAGE:host:h1:loadavg"]}, '
           'data: [{t: 10, values: [0.25, NaN]}, {t: 5, values: [0.1, 1.5]}]}')
    got = {s.name: s.value for s in parse_rrd_updates(doc)}
    assert got == {"cpu_avg": 0.25, "loadavg": 1.5}


def test_unnamed_pool_uses_master_name():
    srv = serve(0, ["127.0.0.1"], name="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mgr = PoolManager([PoolConfig(url=f"http://127.0.0.1:{srv.server_address[1]}",
                                      username="root", password="demo")])
        mgr.poll_once(0)
        assert 'xen_up{pool="xcp-host-1"} 1.0' in _scrape(mgr)
    finally:
        srv.shutdown()
