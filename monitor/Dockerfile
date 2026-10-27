# web: the dashboard. Built from the repository root (docker-compose.yaml) so
# the gateway package travels with it: the topic-prefix rule and the deployment
# reader are shared, not copied. deployments/ is mounted read-only at
# /app/deployments for the surveyed positions on the map.

# Wheels are built in a stage with a compiler: on 32-bit ARM, greenlet (eventlet)
# and msgpack (the InfluxDB client) publish no prebuilt wheel. The image itself
# carries no compiler.
FROM python:3.12-slim AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY monitor/requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY monitor/requirements.txt ./requirements.txt
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt

COPY gateway/ ./gateway/
COPY monitor/ ./monitor/

# It serves a network port and needs no device: no reason to run as root.
RUN useradd --system --no-create-home monitor
USER monitor

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "monitor"]
