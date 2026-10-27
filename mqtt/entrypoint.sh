#!/bin/sh
# Renders the broker ACL for this deployment's topic prefix, then hands over to
# the image's own entrypoint. Rendered at every start from the MQTT_TOPIC_PREFIX
# the gateway and Telegraf also read, so the three cannot drift apart (G4).
set -eu

# Same rule as gateway/publish.py: the value is substituted with sed.
case "${MQTT_TOPIC_PREFIX:-}" in
    "" | *[!A-Za-z0-9._-]*)
        echo "mosquitto: MQTT_TOPIC_PREFIX must be letters, digits, '.', '_' or '-'" \
             "(got '${MQTT_TOPIC_PREFIX:-}')" >&2
        exit 1 ;;
esac

sed "s/{prefix}/${MQTT_TOPIC_PREFIX}/g" /mosquitto/config/aclfile.template > /mosquitto/aclfile
chown mosquitto:mosquitto /mosquitto/aclfile
chmod 0600 /mosquitto/aclfile
echo "mosquitto: ACL rendered for prefix '${MQTT_TOPIC_PREFIX}'"

exec /docker-entrypoint.sh "$@"
