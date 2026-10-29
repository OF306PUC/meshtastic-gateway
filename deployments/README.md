# deployments/

Configuration for the gateway container, together with `.env` (secrets and
host settings). Same schema as `meshtastic-platform`'s `deployments/`.

## Keep each file identical to the platform's copy

The gateway pairs with the platform only through these files: the platform
provisions the radios from its copy, the gateway measures them with this one.
Nothing synchronises the two copies, and nothing fails when they drift:

| If this copy differs in... | the gateway... |
|---|---|
| a node missing, or another `node_id` | drops its packets as an unknown sender |
| a node's label | publishes it under another topic and InfluxDB series |
| a cadence (`intervals`) | charges losses that did not happen, or flags early arrivals (`cadence_violated`) |
| a flow the node does not emit | measures 100 % loss against a cadence the node never had |

Check before every campaign. The two files must have the same SHA-256, which is
also the `sha256` the platform records in a channel-study `session.json`:

    sha256sum deployments/<name>.yaml <platform>/deployments/<name>.yaml

The receiver prints the file's SHA-256 when it starts, and logs a WARNING (once
each) for the drift it can see: a sender that is not in the file, a flow that
arrives with no declared cadence, and a cadence the packets break
(`cadence_violated`). Its periodic report counts what it discarded and why.

## A client's files in their own folder

A deployment can sit in a subfolder: `sasipa/rapa-nui.yaml`, selected with
`MESH_DEPLOYMENT=sasipa/rapa-nui`. Its file name still matches its
`meta.deployment`. The platform keeps its copy at the top of its own
`deployments/`, where its tools look for it, so compare across the two paths:

    sha256sum deployments/sasipa/rapa-nui.yaml <platform>/deployments/rapa-nui.yaml
