# xen-mon

All-in-one monitoring for **XCP-ng** (and Citrix XenServer) pools: deploy one Docker Compose stack, point it at your pool masters, and get Grafana dashboards and alerts in about a minute.

```
 XCP-ng pools ──XAPI/HTTPS──▶ xen-mon exporter ──▶ Prometheus ──▶ Grafana
 (master + every host)        (:9890 /metrics)      (alert rules)   (3 dashboards)
```

![XCP-ng Overview dashboard](docs/screenshots/overview.png)

![XCP-ng VM dashboard](docs/screenshots/vm.png)

- **Agentless.** Nothing is installed on dom0. The exporter logs in to each pool master over the API, discovers every host, VM and SR, and reads the RRD metrics the hosts already record.
- **Multi-pool.** Monitor any number of pools from one stack.
- **Works without Xen Orchestra.** It talks to XAPI directly.
- **Batteries included.** Pre-provisioned Grafana dashboards (Overview, Host, VM) and Prometheus alert rules.

## Deploy

You need a Linux machine or VM with Docker Engine and the Compose plugin (v2.24+). It must be able to reach the management IP of **every** XCP-ng host in your pools on HTTPS (443). You don't need to clone the repo: all three containers are prebuilt images.

### 1. Download two files

```bash
mkdir xen-mon && cd xen-mon
curl -LO https://raw.githubusercontent.com/mspencerl87/xen-mon/main/docker-compose.yml
curl -L -o .env https://raw.githubusercontent.com/mspencerl87/xen-mon/main/.env.example
```

### 2. Point it at your pools

Edit `.env` and set your pool master's address (the XCP-ng host itself, not XOA) and credentials:

```bash
XEN_POOL1_URL=https://192.168.10.10
XEN_POOL1_USERNAME=root
XEN_POOL1_PASSWORD=your-root-password

GRAFANA_ADMIN_PASSWORD=something-strong
```

For more pools, add `XEN_POOL2_URL`, `XEN_POOL2_PASSWORD` and so on. Every host in each pool is discovered automatically. If you'd rather answer prompts, `./setup.sh` writes `.env` for you; it's in the repo, and it fetches `docker-compose.yml` if it's missing.

### 3. Start it

```bash
docker compose up -d
docker compose exec exporter python -m xen_exporter.diagnose   # checks every pool and host
```

Open `http://<docker-host>:3000` and log in as `admin`. The **XCP-ng Overview** dashboard is the home page.

### Changing pools / starting fresh

After editing `.env`, apply the change:

```bash
docker compose up -d
```

Old series, such as a renamed pool or a test pool, stay in Prometheus until they age out (`PROMETHEUS_RETENTION`, 30 days by default) and keep appearing in the Pool picker. To wipe all stored metrics and Grafana state and start clean:

```bash
docker compose down -v      # -v deletes the prometheus-data and grafana-data volumes
docker compose up -d
```

### Updating

```bash
docker compose pull
docker compose up -d
```

Set `XEN_MON_VERSION` in `.env` to a release such as `0.3.0` to pin a version instead of following `latest`.

### Troubleshooting

Start with the built-in check. It logs in to each pool, measures clock skew and fetches performance data from every host:

```bash
docker compose exec exporter python -m xen_exporter.diagnose
```

| Symptom | Cause / fix |
|---|---|
| Every panel says *No data* and *Pools reachable* is 0 | The exporter isn't running. Check `docker compose logs exporter`: "No pools configured" or "Replace POOL-MASTER-IP" means `.env` isn't filled in. |
| *Pools down* is 1 | The exporter can't log in. Check the URL, username and password, and whether the Docker host can reach the master on 443. |
| Memory, VM counts and SR usage work, but CPU, network, disk and SR I/O are *No data* everywhere | Run the diagnose command above; it shows what each host returned. Clock skew between the Docker host and the pool is compensated automatically and logged as `clock skew`. |
| A host shows Memory/VMs but CPU and Load are *No data*, and the Host page shows *Performance data: FAILING* | The exporter can reach the master but not that host's `/rrd_updates`. Fix routing, or map the host to a reachable address with `host_overrides` (see [Advanced configuration](#advanced-configuration-file)). |
| The Pool picker shows the master's host name | The pool has no name in XCP-ng. Set one in XO, or set `XEN_POOL1_NAME` in `.env`. |
| `pull access denied` for a `ghcr.io` image | The image isn't public yet. Set `XEN_MON_REGISTRY=docker.io/mspencerl87` to pull from Docker Hub instead. |

## Configuration

All settings live in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `XEN_POOLn_URL` | none | Pool master address for pool *n* (1, 2, 3...). A pool member also works: it redirects to the master. |
| `XEN_POOLn_USERNAME` | `root` | Login for pool *n* |
| `XEN_POOLn_PASSWORD` | none | Password for pool *n* |
| `XEN_POOLn_NAME` | pool name | Display name for pool *n* |
| `XEN_POOLn_VERIFY_SSL` | `false` | Verify the host TLS certificates (XCP-ng ships self-signed ones) |
| `XEN_INTERVAL` | `30` | Seconds between polls |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | `admin` / `admin` | Grafana login |
| `GRAFANA_PORT` | `3000` | Grafana port |
| `PROMETHEUS_BIND` / `PROMETHEUS_PORT` | `127.0.0.1` / `9090` | Prometheus UI (local only by default) |
| `PROMETHEUS_RETENTION` | `30d` | How long metrics are kept |
| `XEN_MON_VERSION` | `latest` | Image tag for all three images |
| `XEN_MON_REGISTRY` | `ghcr.io/mspencerl87` | Where to pull images from (`docker.io/mspencerl87` for Docker Hub) |

### Advanced configuration file

For `host_overrides` (hosts reachable at a different address than XAPI reports), `password_file`, or shared defaults across many pools, mount a YAML file. Create `docker-compose.override.yml` next to `docker-compose.yml`:

```yaml
services:
  exporter:
    volumes:
      - ./config.yml:/config/config.yml:ro
```

```yaml
# config.yml (see config/config.example.yml)
pools:
  - url: https://10.0.0.20
    password: ${XEN_POOL2_PASSWORD}     # expanded from .env
    host_overrides:
      xcp-lab-02: 10.0.0.22
```

Pools from the file and from `.env` are combined. The same URL listed in both is only polled once.

### Custom alert rules or dashboards

The Prometheus and Grafana images include xen-mon's rules and dashboards. To change the rules, mount your own: add `- ./rules:/etc/prometheus/rules:ro` under `prometheus.volumes` in `docker-compose.override.yml`. Dashboards can be edited in Grafana and saved under a new name.

### Credentials

XAPI only offers role-based access for external (AD/LDAP) users. If your pool uses external authentication, create a user with the **read-only** role for xen-mon. Otherwise use `root`, and keep `.env` readable only by you (`chmod 600 .env`; `setup.sh` does this).

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

### Using only the dashboards

Already running Prometheus and Grafana? Run just the exporter image (`ghcr.io/mspencerl87/xen-mon-exporter`, configured with the same `XEN_POOLn_*` variables), add a scrape job for `<exporter>:9890`, and import the dashboards from grafana.com or from [`grafana/grafana.com/`](grafana/grafana.com). Those copies ask which Prometheus datasource to use when you import them.

## Development

```bash
cd exporter
pip install -r requirements.txt pytest
python -m pytest -q tests                     # unit tests + end-to-end against a fake pool
(cd tests && MOCK_HOSTS=127.0.0.1,localhost MOCK_PORT=18080 python mock_xapi.py &)   # fake pool
XEN_CONFIG=/none XEN_POOL1_URL=http://127.0.0.1:18080 XEN_POOL1_PASSWORD=demo python -m xen_exporter
curl -s localhost:9890/metrics | grep ^xen_ | head
```

To run the whole stack from your checkout (building all three images locally and mounting `config/`):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

The dashboards are generated by `tools/gen_dashboards.py`. Edit that file and re-run it rather than editing the JSON by hand. CI checks that the generated JSON is current, then builds multi-arch (amd64 and arm64) images of the exporter, Prometheus and Grafana, and publishes them to GHCR and Docker Hub. See [docs/publishing.md](docs/publishing.md).

## Roadmap

- Bundled Alertmanager with email, Slack and Teams examples
- Optional Xen Orchestra OpenMetrics source (backups, patches)
- Pending-patch and HA status metrics
- Helm chart

## License

MIT
