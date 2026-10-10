#!/usr/bin/env bash
# Interactive first-time setup for xen-mon: writes config.yml + .env and starts the stack.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "docker is required: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 is required"; exit 1; }

if [[ -f config/config.yml ]]; then
  read -rp "config/config.yml already exists. Overwrite? [y/N] " a
  [[ "${a,,}" == y* ]] || { echo "Keeping existing config. Starting stack..."; docker compose up -d; exit 0; }
fi

echo "== xen-mon setup =="
echo "Add one entry per pool (pool master address). Leave the address empty to finish."
pools_yaml=""
env_lines=""
i=1
while true; do
  read -rp "Pool $i master address (e.g. 192.168.1.10): " addr
  [[ -z "$addr" ]] && break
  read -rp "  Display name [auto]: " name
  read -rp "  Username [root]: " user; user=${user:-root}
  read -rsp "  Password: " pass; echo
  read -rp "  Verify TLS certificate? [y/N] " v; [[ "${v,,}" == y* ]] && verify=true || verify=false
  [[ "$addr" == http* ]] || addr="https://$addr"
  var="XEN_POOL${i}_PASSWORD"
  pools_yaml+="  - url: ${addr}"$'\n'
  [[ -n "$name" ]] && pools_yaml+="    name: \"${name}\""$'\n'
  pools_yaml+="    username: ${user}"$'\n'
  pools_yaml+="    password: \${${var}}"$'\n'
  pools_yaml+="    verify_ssl: ${verify}"$'\n'
  # single-quote the password for the env file
  env_lines+="${var}='${pass//\'/\'\\\'\'}'"$'\n'
  i=$((i+1))
done
[[ -z "$pools_yaml" ]] && { echo "No pools entered, aborting."; exit 1; }

read -rsp "Grafana admin password [admin]: " gpass; echo; gpass=${gpass:-admin}
read -rp "Grafana port [3000]: " gport; gport=${gport:-3000}

cat > config/config.yml <<YAML
interval: 30
pools:
${pools_yaml}
YAML
umask 077
cat > .env <<ENV
${env_lines}GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD='${gpass//\'/\'\\\'\'}'
GRAFANA_PORT=${gport}
PROMETHEUS_BIND=127.0.0.1
PROMETHEUS_PORT=9090
PROMETHEUS_RETENTION=30d
XEN_MON_VERSION=latest
ENV
chmod 600 .env

echo "Starting stack..."
docker compose pull --ignore-buildable 2>/dev/null || docker compose pull --ignore-pull-failures || true
docker compose up -d --build
echo
echo "Done. Open http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):${gport}  (user: admin)"
echo "Check the exporter with: docker compose logs -f exporter"
