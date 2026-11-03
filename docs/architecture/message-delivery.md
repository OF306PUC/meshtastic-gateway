# Confirming that a message arrived (D1 → D2)

**Status: a proposal, not built.** The receipt it describes belongs to the PBX
project's frame protocol; the gateway only records what it hears. The request
went to the PBX project on 2026-11-03 as a shared document, "PBX delivery
receipts"; §3 is its summary.

**The question.** A phone on access node D1 sends a message to a phone on access
node D2. Did it reach D2? This document records what the gateway can and
cannot answer, and what it would take to answer it. The firmware facts come
from the Meshtastic firmware source (`master`, read 2026-11-02); the mesh runs
2.7.26.

---

## 1. What the gateway sees

The gateway is a radio on a serial port (GW, `CLIENT_MUTE`). Three firmware
rules decide what reaches the receiver:

1. **Only broadcasts and packets addressed to the gateway radio.** The
   firmware passes a received packet to its computer only if
   `isBroadcast(mp.to) || isToUs(&mp)` (`RoutingModule::handleReceivedProtobuf`).
   A packet from D1 addressed to D2 is relayed by the mesh, but the gateway's
   computer never receives it.
2. **One copy of each packet.** When other nodes relay a packet, the firmware
   drops the repeated copies before the computer sees them
   (`FloodingRouter::shouldFilterReceived`). The receiver sees the first copy
   that arrived and nothing about the others.
3. **Direct messages are end-to-end encrypted.** Since firmware 2.5 a direct
   message is encrypted with the destination's public key. Even if the gateway
   received a D1 → D2 direct message, it could not read it.

| Traffic | Gateway sees the message | Gateway sees a confirmation |
|---|---|---|
| Channel message (broadcast): an app's text, or a PBX broadcast frame | Yes, if in range | No such thing: a broadcast is never acknowledged |
| Direct message D1 → D2 (app) | No (rule 1) | No: D2's ACK is addressed to D1 |
| Routed PBX frame D1 → D2 (`PRIVATE_APP`, `to` = D2's node num) | No (rule 1) | No: the same ACK, and it covers D2's radio, not the phone |
| Direct message to the gateway radio | Yes | Its own radio sends the ACK; the sender's phone shows ✓ |

So when the gateway is the destination, delivery is already answered: a
message on the Messages page arrived. Between two other points of the mesh, it
is not.

## 2. What Meshtastic offers, and why it does not answer the question

- **A direct message's ACK.** D2's radio answers with a `ROUTING_APP` ACK
  addressed to D1, and D1's phone shows ✓ (after up to three retries, a NAK
  instead). It confirms that D2's *radio* got the message, not that it reached
  the application or phone behind it. Only the sender's phone sees it (rule 1).
- **A channel message's "implicit ACK".** The sender's radio marks a broadcast
  delivered as soon as it hears *any* node relay it. That proves a neighbour
  received it, not D2.
- **`relay_node`** (published since 2026-11-02). The copy the gateway hears
  names the radio that last transmitted it. That relay received the message.
  But this tells you about one relay per message (rule 2). D1, D2 and GW are
  `CLIENT_MUTE`, which never relays, so D2 never shows up as a relay.
- **NeighborInfo** (published since 2026-11-02). It says that D1 and D2 hear a
  common node, and how well. That makes delivery likely, but it is not
  delivery.

## 3. What would confirm it: a receipt on the channel

The phone that receives a message answers it with a short **receipt**,
broadcast on the messaging channel, naming the message it confirms. The
message itself is usually a direct packet the gateway never sees: the PBX app
sends a routed frame `to` D2's node num (meshpbx `docs/client-integration.md`
§4.2). The receipt is a broadcast, so the gateway hears it (rule 1), and it
names the message on its own.

What the request to the PBX project proposes (their call in every point):

- **Who sends it:** the app on the receiving phone, once it has parsed a
  frame whose `DST_ID` is its own `proxy_id`. The alternative is the proxy at
  D2, when it hands the frame to that phone's BLE slot.
- **What it carries:** the PBX ids plus the per-pair sequence number of the
  v2 header meshpbx already proposes (`docs/seq-numbers-pdr.md`), with one
  `TYPE` byte added: `[VERSION 0x02][TYPE][SRC_ID:4][DST_ID:4][SEQ:2]`,
  `TYPE` 0x00 a message, 0x01 a receipt. The receipt swaps the ids, so every
  proxy routes it to the original sender, and repeats the message's `SEQ`. A
  receipt naming the packet id (`pkt_id`) was dropped: the gateway does not
  hear the direct message, so it would have nothing to pair it with, and a
  resend gets a new id.
- **How it is sent:** `to` broadcast, portnum 256, on `EasterNetM`, no
  `want_ack`, the messages' hop limit. A resend of the same message is
  answered again; nobody answers a receipt. The sender may resend after a
  timeout T.
- **Byte order:** the ids are big-endian on the wire (as `proxy_id_value()`
  and `gateway/payload.py` read them), although meshpbx's
  `client-integration.md` says little-endian. The request suggests a
  big-endian `SEQ` too.

**Cost.** A 12-byte receipt makes a LoRa payload of about 35 bytes once the
Meshtastic header (16 bytes) and the `Data` protobuf are added. At
`MEDIUM_FAST` (SF9, 250 kHz, CR 4/5, 16-symbol preamble) that is about
**0.14 s of airtime per transmission**, against 0.19 s for a v2 message with
20 bytes of text. Every node that rebroadcasts it spends that again.

## 4. What the gateway would then do

Nothing below is built: it waits on the receipt format and the day v2 replaces
v1. Until then `gateway/payload.py` rejects any `VERSION` but 1, so a v2 frame
is counted as `malformed`, not misread, and v2 messages would drop off the
Messages page: the gateway has to switch the same day as the phones and the
proxies.

- Decode v1 and v2 frames side by side, and publish receipts beside the
  messages: the `message` topic with a new `origin` (for example `receipt`),
  or a topic of their own.
- Record each receipt by (`SRC_ID`, `DST_ID`, `SEQ`). When the gateway also
  heard the message (a broadcast frame, or one addressed to its radio), pair
  the two and mark it on the Messages page:
  - "✓ received by D2 after 12 s";
  - "no receipt yet";
  - "unconfirmed" once T has passed.
- Keep a delivery ratio per pair of phones from the gaps in confirmed `SEQ`
  values, next to the per-node PDR.

There are two limits, both because the gateway is only an observer:

- **The gateway hears the receipt but not the message.** This is the usual
  case. It still learns that the phone behind D2 received message `SEQ` from
  the phone behind D1, because the receipt says so.
- **A receipt is missing.** The gateway cannot tell a lost message from a lost
  receipt or a receipt it did not hear. It reports the message as
  **unconfirmed**, never as lost.
