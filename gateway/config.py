"""The receiver's settings, from the environment (.env and secrets/gateway.env).

Whatever could silently point at the wrong mesh, topic namespace or radio is
required. Harmless settings have defaults, as in the monorepo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from gateway.decode import FLOW_KINDS
from gateway.deployment import ENV_DEPLOYMENT
from gateway.publish import topic_prefix_from_env

__all__ = ["Config", "ConfigError", "from_env"]

DEFAULT_PDR_WINDOW_SEC = 3600
DEFAULT_SWEEP_INTERVAL_SEC = 30


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    deployment: str
    topic_prefix: str
    serial_port: str
    broker_address: str
    broker_port: int
    client_id: str
    username: str
    password: str
    pdr_window_sec: Mapping[str, int]
    sweep_interval_sec: int


def _required(env: Mapping[str, str], name: str, why: str) -> str:
    if not env.get(name):
        raise ConfigError(f"{name} is not set: {why}")
    return env[name]


def _seconds(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ConfigError(f"{name}: expected a positive number of seconds, got {raw!r}")
    return value


def from_env(environ: Mapping[str, str] = os.environ) -> Config:
    try:
        prefix = topic_prefix_from_env(environ)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    window = _seconds(environ, "PDR_WINDOW_SEC", DEFAULT_PDR_WINDOW_SEC)
    try:
        port = int(environ.get("BROKER_PORT") or 1883)
    except ValueError:
        raise ConfigError(f"BROKER_PORT: expected a port number, "
                          f"got {environ['BROKER_PORT']!r}") from None
    return Config(
        deployment=_required(environ, ENV_DEPLOYMENT, "which deployments/ file describes the mesh"),
        topic_prefix=prefix,
        serial_port=_required(environ, "GATEWAY_SERIAL_PORT",
                              "the gateway radio's serial device (prefer /dev/serial/by-id/...)"),
        broker_address=environ.get("BROKER_ADDRESS") or "localhost",
        broker_port=port,
        # Two clients with one id knock each other off the broker in a loop.
        client_id=environ.get("CLIENT_ID") or f"{prefix}-gateway",
        username=environ.get("MQTT_USERNAME_GATEWAY") or environ.get("MQTT_USERNAME", ""),
        password=environ.get("MQTT_PASSWORD_GATEWAY") or environ.get("MQTT_PASSWORD", ""),
        pdr_window_sec={k: _seconds(environ, f"PDR_WINDOW_SEC_{k.upper()}", window)
                        for k in FLOW_KINDS},
        sweep_interval_sec=_seconds(environ, "PDR_SWEEP_INTERVAL_SEC", DEFAULT_SWEEP_INTERVAL_SEC),
    )
