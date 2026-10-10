# Prometheus with xen-mon's scrape config and alert rules built in.
FROM prom/prometheus:v3.1.0

LABEL org.opencontainers.image.source="https://github.com/mspencerl87/xen-mon" \
      org.opencontainers.image.description="Prometheus preconfigured for xen-mon (XCP-ng monitoring)" \
      org.opencontainers.image.licenses="MIT"

COPY prometheus.yml /etc/prometheus/prometheus.yml
COPY rules/ /etc/prometheus/rules/
