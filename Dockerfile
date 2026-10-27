# gateway-receiver: main.py beside the gateway package, as it runs from a clone.
# deployments/ is mounted read-only at /app/deployments by docker-compose.yaml.

# Wheels are built in a stage with a compiler: on 32-bit ARM some dependencies
# (dbus-fast, through meshtastic) publish no prebuilt wheel. The image itself
# carries no compiler.
FROM python:3.12-slim AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt

COPY gateway/ ./gateway/
COPY main.py ./

# It parses packets from anyone in radio range: no root. The serial device keeps
# the host's ownership, root:dialout (gid 20 on Debian, Ubuntu and Raspberry Pi
# OS), and this user is in that group.
RUN useradd --system --no-create-home --groups dialout gateway
USER gateway

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
