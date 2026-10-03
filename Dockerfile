FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

LABEL org.opencontainers.image.title="DouYinSparkFlow Single-user" \
      org.opencontainers.image.source="https://github.com/BARONCMH/DouYinSparkFlow-SingleUser" \
      org.opencontainers.image.description="Local single-user DouYinSparkFlow panel for multiple Douyin accounts"

ENV PYTHONUNBUFFERED=1 \
    PANEL_HOST=0.0.0.0 \
    DSF_BASE_DIR=/app/single-user/runtime \
    DSF_CONFIG_DIR=/app/single-user/data/config \
    DSF_LOG_DIR=/app/single-user/data/logs

WORKDIR /app/single-user
COPY requirements-windows.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app/single-user

EXPOSE 18081
CMD ["python", "panel.py"]
