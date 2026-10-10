#!/usr/bin/env bash
# Interactive first-time setup for xen-mon: writes .env and starts the stack.
# Works in a git checkout or in a folder containing only docker-compose.yml.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "docker is required: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "the docker compose plugin (v2.24+) is required"; exit 1; }
[[ -f docker-compose.yml ]] || curl -fsSLO https://raw.githubusercontent.com/mspencerl87/xen-mon/main/docker-compose.yml

if [[ -f .env ]]; then
  read -rp ".env already exists. Overwrite? [y/N] " a
  [[ "${a,,}" == y* ]] || { echo "Keeping existing .env. Starting stack..."; docker compose up -d; exit 0; }
fi

q() { printf "'%s'" "${1//\'/\'\\\'\'}"; }   # single-quote a value for .env

echo "== xen-mon setup =="
echo "Enter each pool's master address (the XCP-ng host, not XOA). Leave empty to finish."
env_pools=""
i=1
while true; do
  read -rp "Pool $i master address (e.g. 192.168.1.10): " addr
  [[ -z "$addr" ]] && break
  [[ "$addr" == http* ]] || addr="https://$addr"
  read -rp "  Display name [auto]: " name
  read -rp "  Username [root]: " user; user=${user:-root}
  read -rsp "  Password: " pass; echo
  read -rp "  Verify TLS certificate? [y/N] " v; [[ "${v,,}" == y* ]] && verify=true || verify=false
  env_pools+="XEN_POOL${i}_URL=${addr}"$'\n'
  env_pools+="XEN_POOL${i}_USERNAME=$(q "$user")"$'\n'
  env_pools+="XEN_POOL${i}_PASSWORD=$(q "$pass")"$'\n'
  env_pools+="XEN_POOL${i}_VERIFY_SSL=${verify}"$'\n'
  [[ -n "$name" ]] && env_pools+="XEN_POOL${i}_NAME=$(q "$name")"$'\n'
  i=$((i+1))
done
[[ -z "$env_pools" ]] && { echo "No pools entered, aborting."; exit 1; }

read -rsp "Grafana admin password [admin]: " gpass; echo; gpass=${gpass:-admin}
read -rp "Grafana port [3000]: " gport; gport=${gport:-3000}

umask 077
cat > .env <<ENV
${env_pools}XEN_INTERVAL=30
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=$(q "$gpass")
GRAFANA_PORT=${gport}
PROMETHEUS_BIND=127.0.0.1
PROMETHEUS_PORT=9090
PROMETHEUS_RETENTION=30d
XEN_MON_VERSION=latest
ENV
chmod 600 .env

echo "Starting stack..."
docker compose pull
docker compose up -d
echo
echo "Done. Open http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):${gport}  (user: admin)"
echo "Check the connection with: docker compose exec exporter python -m xen_exporter.diagnose"
