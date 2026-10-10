# Grafana with xen-mon's datasource and dashboards provisioned.
FROM grafana/grafana:11.4.0

LABEL org.opencontainers.image.source="https://github.com/mspencerl87/xen-mon" \
      org.opencontainers.image.description="Grafana with xen-mon XCP-ng dashboards preinstalled" \
      org.opencontainers.image.licenses="MIT"

# Dashboards live outside /var/lib/grafana (a volume), so image updates
# always ship the latest dashboards.
COPY provisioning/ /etc/grafana/provisioning/
COPY dashboards/ /etc/xen-mon/dashboards/

ENV GF_USERS_ALLOW_SIGN_UP=false \
    GF_ANALYTICS_REPORTING_ENABLED=false \
    GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/etc/xen-mon/dashboards/xen-overview.json
