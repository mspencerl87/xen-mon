# Publishing xen-mon

This page is for maintainers. It covers the one-time setup that lets CI publish images, and how to list the dashboards on grafana.com.

## Container images

On every push to `main` (and on every `v*` tag), CI builds three multi-arch images (amd64 and arm64) and pushes them:

| Image | GHCR | Docker Hub |
|---|---|---|
| exporter | `ghcr.io/mspencerl87/xen-mon-exporter` | `docker.io/<user>/xen-mon-exporter` |
| prometheus | `ghcr.io/mspencerl87/xen-mon-prometheus` | `docker.io/<user>/xen-mon-prometheus` |
| grafana | `ghcr.io/mspencerl87/xen-mon-grafana` | `docker.io/<user>/xen-mon-grafana` |

### GHCR (one time)

GHCR packages start out **private**. After the first successful CI run, go to github.com → your profile → **Packages**, and for each of the three `xen-mon-*` packages: **Package settings → Change visibility → Public**. While you're there, under **Manage Actions access**, check that the `xen-mon` repository has **Write** access.

### Docker Hub (one time)

1. Sign in at hub.docker.com (create a free account if needed).
2. **Account settings → Personal access tokens → Generate new token**. Set access permissions to **Read, Write, Delete**; "Delete" is needed so CI can update the repository descriptions.
3. In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `DOCKERHUB_USERNAME`: your Docker Hub username
   - `DOCKERHUB_TOKEN`: the token from step 2
4. Re-run CI: **Actions → ci → Run workflow**.

Docker Hub repositories are created automatically on the first push and are public by default on free accounts. CI also sets each repository's description from [`DOCKERHUB.md`](../DOCKERHUB.md).

If your Docker Hub username isn't `mspencerl87`, replace it in `DOCKERHUB.md`, `.env.example` and the README.

### Releases

```bash
git tag v0.3.0
git push origin v0.3.0
```

This publishes `0.3.0` and `0.3` tags alongside `latest`. Users pin a release with `XEN_MON_VERSION=0.3.0` in `.env`.

## grafana.com dashboards

grafana.com hosts dashboards that anyone can import by ID. The files to upload are in [`grafana/grafana.com/`](../grafana/grafana.com); they ask for a Prometheus datasource on import. Upload each one separately:

1. Sign in at grafana.com (a free account works).
2. Go to **grafana.com/orgs/<your-org>/dashboards/new**, or **My Account → Dashboards → Upload dashboard**.
3. Upload `xen-overview.json`, then fill in the listing using the text below.
4. In the listing's **Images** section, upload `docs/screenshots/overview.png` (and `vm.png` for the VM dashboard).
5. Repeat for `xen-host.json` and `xen-vm.json`.

After publishing, note each dashboard's ID (in its URL, e.g. `.../dashboards/12345`) and add the IDs to the README so people can use **Dashboards → New → Import → ID**.

When you change a dashboard, regenerate it (`python tools/gen_dashboards.py`) and upload the new JSON as a **new revision** of the same listing.

### Listing text

**Name:** `XCP-ng Overview (xen-mon)`

**Description:**

```markdown
Overview of XCP-ng / XenServer pools: pool and host health, VM counts, host CPU and memory, storage repository usage, latency, IOPS and throughput, and the top 10 VMs by CPU, memory, network and disk. Click any host or VM to drill down.

Data comes from the **xen-mon** exporter, which reads metrics straight from XAPI with no agent on dom0. The full stack (exporter + Prometheus + Grafana with these dashboards preinstalled) deploys with `docker compose up -d`.

Setup, docs and source: https://github.com/mspencerl87/xen-mon

Companion dashboards: XCP-ng Host (xen-mon), XCP-ng VM (xen-mon).
```

**Name:** `XCP-ng Host (xen-mon)`

**Description:**

```markdown
Per-host view for XCP-ng / XenServer: status, per-core CPU, load, memory and dom0 memory, network per PIF, storage I/O per SR (throughput, IOPS, latency, IO wait), and the VMs running on the host.

Requires the xen-mon exporter: https://github.com/mspencerl87/xen-mon
```

**Name:** `XCP-ng VM (xen-mon)`

**Description:**

```markdown
Per-VM view for XCP-ng / XenServer: power state, vCPU usage, guest memory (needs guest tools), network per VIF, and disk throughput, IOPS and latency per device.

Requires the xen-mon exporter: https://github.com/mspencerl87/xen-mon
```

**Tags:** `xcp-ng`, `xenserver`, `xen`, `virtualization`, `prometheus`
