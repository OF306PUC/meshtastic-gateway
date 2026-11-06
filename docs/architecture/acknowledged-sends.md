# Sending to one node and confirming it arrived

**Status: future work, urgent (user, 2026-11-05). Not built.** It is not for
the Rapa Nui deployment: `sasipa/rapa-nui` stays receive-only.

**The goal.** The gateway sends a message addressed to one node, and learns
from the ROUTING_APP acknowledgement whether that node received it.

The firmware facts come from the Meshtastic firmware 2.7 source
(`ReliableRouter.cpp`, `NextHopRouter.cpp`, `RoutingModule.cpp`, read
2026-11-05). The library facts come from `meshtastic` 2.7.8, the version in
`requirements.txt`. The mesh runs firmware 2.7.26.

---

## 1. What the gateway does today

- **It never transmits.** No code calls `sendData` or `sendText`; the radio
  only listens.
- **A message addressed to the gateway reaches the receiver.** It is published
  as `message` when it is `TEXT_MESSAGE_APP` or `PRIVATE_APP` from a node in
  the deployment file.
- **The gateway's radio sends the ACK for that message itself**
  (`ReliableRouter::sniffReceived`). It is a packet the radio transmits, so it
  never passes through the computer. The sender sees the message delivered; the
  gateway records nothing about the ACK.
- **A ROUTING_APP addressed to the gateway's radio reaches the receiver.** The
  receiver only counts it (`unknown_portnum["ROUTING_APP"]`,
  `discarded["not_published:other"]`); it neither publishes nor stores it. None
  is expected, since the gateway sends nothing. pi7's report showed none on
  2026-11-04.
- **ACKs between other nodes never reach the gateway.** D2's ACK to D1 is
  neither a broadcast nor addressed to the gateway
  ([message-delivery.md](message-delivery.md) §1).

## 2. What the firmware does with a send that asks for an ACK

- **The gateway's role does not prevent sending.** `CLIENT_MUTE` only stops a
  radio from rebroadcasting other nodes' packets. It still sends its own
  packets and its ACKs.
- **The real ACK.** The recipient's radio answers a `want_ack` packet
  addressed to it with a ROUTING_APP packet:
  - `errorReason: NONE`;
  - `requestId` set to the id of the packet it acknowledges;
  - addressed to the gateway's radio, so it reaches the computer;
  - sent with the hops the request used plus 2, capped at the recipient's
    `hop_limit` (`RoutingModule::getHopLimitForResponse`).

  A direct text message (`TEXT_MESSAGE_APP`) is acknowledged with an ACK that
  itself asks for an ACK.
- **The implicit ACK.** The gateway's radio may hear a neighbour rebroadcast
  the gateway's own packet. It then generates an ACK `NONE` locally, whose
  `from` is the gateway's radio (`ReliableRouter::shouldFilterReceived`). That
  ACK only says a neighbour relayed the packet. Only an ACK whose `from` is the
  recipient confirms delivery. The library draws the same line in
  `Node.onAckNak`: "Received an implicit ACK. Packet will likely arrive, but
  cannot be guaranteed."
- **No ACK.** The radio retransmits (`NUM_RELIABLE_RETX = 3`). Then it hands
  the computer a NAK with `MAX_RETRANSMIT` (`NextHopRouter`).
- **Other NAKs.** `NO_CHANNEL` means the recipient could not decrypt the
  packet. `PKI_UNKNOWN_PUBKEY` means the recipient does not know the sender's
  key.

## 3. What to build

1. **A way to ask the gateway to send.** Decide who asks: the dashboard, an
   MQTT command topic, or the PBX. Any of them needs authentication; only the
   proxy is reachable from the network (G13). An MQTT command topic also needs
   an ACL entry for the gateway to subscribe to it.
2. **The send itself.** Call `iface.sendData(data, destinationId=<node>,
   portNum=…, wantAck=True, channelIndex=…)`, and keep the id of the packet it
   returns.
3. **Pairing.** Pair each ROUTING_APP with its pending send by `requestId`, and
   classify the outcome:

   | Outcome | How to recognise it |
   |---|---|
   | Delivered | `NONE`, and `from` is the recipient |
   | Relayed only | `NONE`, and `from` is the gateway's radio (implicit ACK) |
   | Failed | a NAK; record its reason |
   | No answer | nothing arrived within a timeout |
   | Unknown request | a `requestId` that matches no pending send: count it |
4. **Keep the implicit ACK.** `Receiver._receive` discards every packet whose
   `from` is its own radio before counting it. That check would also drop the
   implicit ACK.
5. **Decode ROUTING_APP.** `decode()` treats it as `other` today. Publish each
   outcome, store it (a Telegraf input and an InfluxDB measurement) and show it
   on the dashboard.
6. **Tests with fixture packets.** Cover a real ACK, an implicit ACK, a
   `MAX_RETRANSMIT` NAK, an ACK for an unknown request, and a send with no
   answer.

## 4. Decisions to take before building

- **The measurement it disturbs (I5, G6).** Every send and its retransmissions
  add airtime and collisions to the mesh whose PDR the gateway measures.
  Either use a second radio for sending, or record every send so the analysis
  can exclude those windows.
- **Reach.** The gateway radio's `hop_limit` (1 in `rapa-nui.yaml`) caps how
  far a send travels: it reaches only nodes at most one relay away. The ACK
  comes back with the recipient's hop budget, which may be larger.
- **Encryption.** Direct messages are encrypted with the recipient's public
  key, which the gateway's radio learns from that node's NodeInfo. A node the
  radio has not heard announce itself cannot get a PKI-encrypted message.
- **Channel and portnum** for the sends, per deployment.
- **Which mesh first.** Rapa Nui is ruled out.
- **The PBX delivery receipt ([message-delivery.md](message-delivery.md) §3)
  is a separate feature.** It confirms phone-to-phone messages, which the
  gateway does not send. This one confirms only the gateway's own sends.
  Neither replaces the other.
