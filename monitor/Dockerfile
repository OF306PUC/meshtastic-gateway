# web: the dashboard. Built from the repository root (docker-compose.yaml) so
# the gateway package travels with it: the topic-prefix rule and the deployment
# reader are shared, not copied. deployments/ is mounted read-only at
# /app/deployments for the surveyed positions on the map.
FROM python:3.12-slim

WORKDIR /app

COPY monitor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ ./gateway/
COPY monitor/ ./monitor/

# It serves a network port and needs no device: no reason to run as root.
RUN useradd --system --no-create-home monitor
USER monitor

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "monitor"]
