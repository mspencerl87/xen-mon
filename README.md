# xen-mon

All-in-one monitoring for **XCP-ng** (and Citrix XenServer) pools: deploy one Docker Compose stack, point it at your pool masters, and get Grafana dashboards and alerts in about a minute.

```
 XCP-ng pools ──XAPI/HTTPS──▶ xen-mon exporter ──▶ Prometheus ──▶ Grafana
 (master + every host)        (:9890 /metrics)      (alert rules)   (3 dashboards)
```

- **Agentless.** Nothing is installed on dom0. The exporter logs in to each pool master over the API, discovers every host, VM and SR, and reads the RRD metrics the hosts already record.
- **Multi-pool.** Monitor any number of pools from one stack.
- **Works without Xen Orchestra.** It talks to XAPI directly.
- **Batteries included.** Pre-provisioned Grafana dashboards (Overview, Host, VM) and Prometheus alert rules.

## Quick start

Requirements: a Linux box or VM with Docker Engine and Compose v2.24+, and HTTPS (443) access to the management IP of every host in your pools.

```bash
git clone https://github.com/mspencerl87/xen-mon.git
cd xen-mon
./setup.sh            # asks for pool address/credentials, writes config, starts the stack
```

Then open `http://<docker-host>:3000` and log in with `admin` and the password you chose.

### Manual setup

```bash
cp config/config.example.yml config/config.yml   # add your pools
cp .env.example .env                             # passwords, Grafana admin, ports
docker compose up -d
docker compose logs -f exporter                  # should show "polled N samples ... (up=1)"
```

### Try it with no pool (demo)

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

This starts a fake two-host pool with generated data so you can explore the dashboards.

## Configuration

`config/config.yml`:

```yaml
interval: 30
defaults:
  username: root
  verify_ssl: false
pools:
  - url: https://192.168.1.10          # pool master (a member works too: it redirects)
    password: ${XEN_POOL1_PASSWORD}    # expanded from .env
  - url: https://10.0.0.20
    name: lab                          # optional display name (defaults to pool name)
    password_file: /run/secrets/lab
    host_overrides:                    # if hosts aren't reachable at their XAPI address
      xcp-lab-02: 10.0.0.22
```

For a single pool you can skip the file and set `XEN_URL`, `XEN_USERNAME` and `XEN_PASSWORD` in `.env` (`XEN_URL` accepts a comma-separated list).

| `.env` variable | Default | Purpose |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `GRAFANA_PORT` | `3000` | Grafana port |
| `PROMETHEUS_BIND` / `PROMETHEUS_PORT` | `127.0.0.1` / `9090` | Prometheus UI (local only by default) |
| `PROMETHEUS_RETENTION` | `30d` | How long metrics are kept |
| `XEN_MON_VERSION` | `latest` | Exporter image tag |

### Credentials

XAPI only offers role-based access for external (AD/LDAP) users. If your pool uses external authentication, create a user with the **read-only** role for xen-mon. Otherwise use `root` and keep `.env` readable only by you (`setup.sh` sets mode 600).

### Network

The exporter needs to reach:
- the **pool master** on 443 for the API, and
- **every host** on 443 for `/rrd_updates`. Each host only reports itself and the VMs running on it.

If a host's address isn't reachable from the Docker host, its panels stay empty and the `XenHostMetricsMissing` alert fires. Fix routing or use `host_overrides`.

## What you get

**Dashboards** (Grafana folder *XCP-ng*):
- **Overview:** pool and host health, VM counts, host CPU and memory, SR usage, latency, IOPS and throughput, top 10 VMs by CPU, memory, network and disk. Click a host or VM to drill down.
- **Host:** per-core CPU, load, memory, dom0 memory, network per PIF, per-SR I/O from that host, and the VMs on it.
- **VM:** vCPU usage, guest memory, and network and disk per device (throughput, IOPS, latency).

**Alerts** (`prometheus/rules/xen.yml`): pool unreachable, exporter down, host not live or disabled, missing host metrics, host CPU above 90%, host memory below 5% free, SR above 85% or 95% full, SR latency above 50 ms, dom0 memory above 90%. You can view them in Prometheus (`http://localhost:9090/alerts`) or in Grafana's alerting UI. To get notifications, add Alertmanager or set up Grafana contact points.

### Metrics

All metrics are prefixed `xen_` and labelled with `pool`, plus `host`/`host_uuid`, `vm`/`vm_uuid`/`is_dom0` or `sr`/`sr_uuid` as appropriate.

| Source | Examples |
|---|---|
| Inventory (XAPI) | `xen_up`, `xen_host_live`, `xen_host_enabled`, `xen_host_memory_{total,free}_bytes`, `xen_vm_running`, `xen_vm_vcpus`, `xen_sr_{size,used,allocated}_bytes`, `xen_*_info` |
| Host RRD | `xen_host_cpu_usage{cpu}`, `xen_host_cpu_avg`, `xen_host_loadavg`, `xen_host_pif_{rx,tx}_bytes{pif}`, `xen_host_sr_{iops_read,iops_write,io_throughput_read,latency,iowait,...}{sr}` |
| VM RRD | `xen_vm_vcpu_usage{vcpu}`, `xen_vm_memory`, `xen_vm_memory_internal_free` (KiB, needs guest tools), `xen_vm_vif_{rx,tx}_bytes{vif}`, `xen_vm_vbd_{read,write}_bytes{device}`, `xen_vm_vbd_{read,write}_latency` (µs) |

Any other RRD data source is exported as `xen_host_<name>` or `xen_vm_<name>`, so nothing is dropped. Units follow XAPI: CPU is a 0–1 fraction, network and disk are bytes/s, SR throughput is MiB/s, and SR latency is in ms.

## Development

```bash
cd exporter
pip install -r requirements.txt pytest
python -m pytest -q tests                     # unit tests + end-to-end against the fake pool
MOCK_HOSTS=127.0.0.1,localhost MOCK_PORT=18080 python -m xen_exporter.mock &
XEN_CONFIG=/none XEN_URL=http://127.0.0.1:18080 XEN_PASSWORD=demo python -m xen_exporter
curl -s localhost:9890/metrics | grep ^xen_ | head
```

The dashboards are generated by `tools/gen_dashboards.py`. Edit that file and re-run it rather than editing the JSON by hand. CI checks that the generated JSON is current, and pushes multi-arch exporter images to `ghcr.io/mspencerl87/xen-mon-exporter`.

## Roadmap

- Bundled Alertmanager with email, Slack and Teams examples
- Optional Xen Orchestra OpenMetrics source (backups, patches)
- Pending-patch and HA status metrics
- Helm chart

## License

MIT
