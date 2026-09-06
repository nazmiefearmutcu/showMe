"""FlowMap depth-heatmap data server, embedded in the showMe sidecar.

This package ports the protocol-compatible core of the standalone FlowMap
server (``flowmap_server``) so the sidecar can serve the FLW pane from
Binance public data:

- :mod:`.events` — canonical in-process event representations.
- :mod:`.wire` — the byte-exact binary framing (8-byte LE envelope).
- :mod:`.binance_feed` — Binance public book/aggTrade/1s-kline feed with the
  official snapshot+diff synchronization (transport injectable for tests).
- :mod:`.grid` — time-weighted density grid with epochs and the f16 ring.
- :mod:`.session` — per-symbol sessions, per-client TX queues, feed hub.

The upstream reference lives in the FlowMap repo (READ-ONLY); this port is
dependency-identical to the sidecar (numpy, no msgspec — cold JSON payloads
are hand-encoded to be byte-identical with msgspec's compact output).
"""
from __future__ import annotations

PROTOCOL_VERSION = 1

__all__ = ["PROTOCOL_VERSION"]
