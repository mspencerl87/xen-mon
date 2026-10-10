# xen-mon: XCP-ng monitoring

All-in-one monitoring for **XCP-ng** (and Citrix XenServer) pools: an agentless exporter, Prometheus and Grafana with ready-made dashboards and alerts, deployed with one `docker compose up -d`.

![XCP-ng Overview dashboard](https://raw.githubusercontent.com/mspencerl87/xen-mon/main/docs/screenshots/overview.png)

The stack is made of three images:

| Image | What it is |
|---|---|
| `xen-mon-exporter` | Logs in to each pool master over XAPI, discovers every host, VM and SR, and exposes their metrics for Prometheus on `:9890`. Nothing is installed on dom0. |
| `xen-mon-prometheus` | Prometheus with the scrape config and XCP-ng alert rules built in |
| `xen-mon-grafana` | Grafana with the Overview, Host and VM dashboards provisioned |

## Quick start

```bash
mkdir xen-mon && cd xen-mon
curl -LO https://raw.githubusercontent.com/mspencerl87/xen-mon/main/docker-compose.yml
curl -L -o .env https://raw.githubusercontent.com/mspencerl87/xen-mon/main/.env.example
# edit .env: XEN_POOL1_URL, XEN_POOL1_PASSWORD, GRAFANA_ADMIN_PASSWORD
# add XEN_MON_REGISTRY=docker.io/mspencerl87 to pull these images from Docker Hub
docker compose up -d
```

Then open `http://<docker-host>:3000`.

Tags: `latest` follows the main branch; `X.Y.Z` and `X.Y` are releases. Images are built for `linux/amd64` and `linux/arm64`.

**Docs, source and issues:** https://github.com/mspencerl87/xen-mon
