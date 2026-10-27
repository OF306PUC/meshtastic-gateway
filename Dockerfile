# gateway-receiver: main.py beside the gateway package, as it runs from a clone.
# deployments/ is mounted read-only at /app/deployments by docker-compose.yaml.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ ./gateway/
COPY main.py ./

# It parses packets from anyone in radio range: no root. The serial device keeps
# the host's ownership, root:dialout (gid 20 on Debian, Ubuntu and Raspberry Pi
# OS), and this user is in that group.
RUN useradd --system --no-create-home --groups dialout gateway
USER gateway

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
