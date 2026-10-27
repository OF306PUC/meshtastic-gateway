#!/usr/bin/env bash
#
# Creates every credential of the stack in one run, so they cannot disagree (G5):
#
#   mqtt/pwfile            the broker's hashed MQTT accounts
#   secrets/<service>.env  one file per container, holding only what it uses
#
# Run it ONCE, before the first `docker compose up`: InfluxDB creates its
# accounts from secrets/influxdb.env on its first start only. Nothing has to be
# copied by hand; the only password printed is the dashboard's, to hand out.
#
# Requires: docker, openssl. mosquitto_passwd and the bcrypt hasher come from
# the broker's and the proxy's images, so nothing has to be installed on the host.

set -euo pipefail

cd "$(dirname "$0")/.."
PWFILE="mqtt/pwfile"
SECRETS="secrets"
IMAGE="eclipse-mosquitto:2.0"
CADDY_IMAGE="caddy:2.10-alpine"   # = the proxy in docker-compose.yaml

# Keep in sync with mqtt/aclfile.template — an account here without a rule
# there can connect but cannot read or write anything.
ACCOUNTS=(gateway telegraf monitor)

for existing in "$PWFILE" "$SECRETS"; do
    if [[ -e "$existing" ]]; then
        echo "error: $existing already exists. Credentials are created together or" >&2
        echo "not at all: delete mqtt/pwfile AND secrets/ deliberately first. After" >&2
        echo "InfluxDB's first start, its accounts also have to change inside the" >&2
        echo "database (docs/troubleshooting.md, 'Rotating the credentials')." >&2
        exit 1
    fi
done

# Everything is built here and moved into place only once all of it exists, so
# a failure half-way leaves nothing behind and the script can simply run again.
umask 077
STAGE=$(mktemp -d "./.credentials.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/secrets"

# 24 alphanumerics: nothing that would need quoting inside an env file.
password() { openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 24; }

declare -A PASS
for account in "${ACCOUNTS[@]}"; do
    PASS[$account]=$(password)
done
INFLUX_ADMIN=$(password)
INFLUX_WRITE=$(password)
INFLUX_READ=$(password)
DASHBOARD_PASSWORD=$(password)
DASHBOARD_HASH=$(docker run --rm "$CADDY_IMAGE" caddy hash-password --plaintext "$DASHBOARD_PASSWORD")

# mosquitto_passwd runs as the host user, so the staged file stays removable.
#   * It does NOT accept combined short options: "-cb" is rejected with a usage
#     dump, so -c and -b are separate, and -c is used once, for the first account.
#   * --entrypoint bypasses the image's docker-entrypoint.sh, which would chown
#     the mounted directory to uid 1883.
first=1
for account in "${ACCOUNTS[@]}"; do
    if [[ $first == 1 ]]; then args=(-c -b); first=0; else args=(-b); fi
    docker run --rm --user "$(id -u):$(id -g)" \
        --entrypoint mosquitto_passwd \
        -v "$PWD/$STAGE:/stage" "$IMAGE" \
        "${args[@]}" /stage/pwfile "$account" "${PASS[$account]}"
done

# One file per container: a compromised one learns only its own credentials.
cat > "$STAGE/secrets/influxdb.env" <<EOF
# Read by influxdb on its FIRST start (empty volume) to create these accounts.
INFLUXDB_ADMIN_USER=admin
INFLUXDB_ADMIN_PASSWORD=$INFLUX_ADMIN
INFLUXDB_WRITE_USER=telegraf
INFLUXDB_WRITE_USER_PASSWORD=$INFLUX_WRITE
INFLUXDB_READ_USER=monitor
INFLUXDB_READ_USER_PASSWORD=$INFLUX_READ
EOF
cat > "$STAGE/secrets/telegraf.env" <<EOF
MQTT_USERNAME_TELEGRAF=telegraf
MQTT_PASSWORD_TELEGRAF=${PASS[telegraf]}
INFLUXDB_WRITE_USER=telegraf
INFLUXDB_WRITE_USER_PASSWORD=$INFLUX_WRITE
EOF
cat > "$STAGE/secrets/gateway.env" <<EOF
MQTT_USERNAME_GATEWAY=gateway
MQTT_PASSWORD_GATEWAY=${PASS[gateway]}
EOF
cat > "$STAGE/secrets/web.env" <<EOF
MQTT_USERNAME_MONITOR=monitor
MQTT_PASSWORD_MONITOR=${PASS[monitor]}
INFLUXDB_READ_USER=monitor
INFLUXDB_READ_USER_PASSWORD=$INFLUX_READ
EOF
cat > "$STAGE/secrets/proxy.env" <<EOF
DASHBOARD_USER=dashboard
# Keep the single quotes: unquoted, docker compose expands the \$ signs in the
# hash and the dashboard rejects every password.
DASHBOARD_PASSWORD_HASH='$DASHBOARD_HASH'
EOF

mv "$STAGE/secrets" "$SECRETS"
mv "$STAGE/pwfile" "$PWFILE"

# The broker reads its password file as uid 1883, which is not the host user —
# hence the root container rather than a plain chmod. Mosquitto 2.x warns on
# world-readable credential files, and future versions will refuse them.
docker run --rm -v "$PWD/mqtt:/x" alpine:3 sh -c \
    'chown 1883:1883 /x/pwfile && chmod 0600 /x/pwfile'

cat <<EOF

Created $PWFILE and $SECRETS/ (influxdb, telegraf, gateway, web, proxy).

Dashboard login: user 'dashboard', password $DASHBOARD_PASSWORD
Note it now and give it to whoever opens the dashboard: it is stored nowhere.
The InfluxDB admin account (maintenance only) is in $SECRETS/influxdb.env.

Then:   docker compose up -d --force-recreate
Verify: docker compose logs telegraf | grep -i connect
        docker compose logs gateway-receiver | grep MQTT
A rc=5 or "not authorized" in either means a credential did not match.
EOF
