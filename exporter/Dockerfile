FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/mspencerl87/xen-mon" \
      org.opencontainers.image.description="Prometheus exporter for XCP-ng / XenServer pools" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY xen_exporter ./xen_exporter

RUN useradd --system --uid 10001 exporter
USER exporter
EXPOSE 9890
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:9890/metrics', timeout=4)" || exit 1
ENTRYPOINT ["python", "-m", "xen_exporter"]
