"""Client IP resolution with an explicit trusted-proxy list."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from typing import Any

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(items: Iterable[str]) -> list[Network]:
    """Parse IP/CIDR strings; raises ``ValueError`` on malformed entries."""

    return [ipaddress.ip_network(item, strict=False) for item in items]


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address,
                trusted: Iterable[Network]) -> bool:
    return any(address in network for network in trusted)


def resolve_client_ip(
    scope: Mapping[str, Any],
    trusted: Iterable[Network] = (),
) -> str:
    """Return the client address used for rate limiting.

    ``X-Forwarded-For`` is honoured only when the direct peer is in
    ``trusted``. The header is then walked right to left and the first hop that
    is not itself a trusted proxy wins, so a client cannot spoof its address by
    prepending entries. A malformed hop stops the walk at the last trusted hop.
    """

    client = scope.get("client")
    peer = client[0] if client else "unknown"
    trusted = list(trusted)
    peer_ip = _parse(peer)
    if peer_ip is None or not trusted or not _is_trusted(peer_ip, trusted):
        return peer

    forwarded = [
        value.decode("latin-1")
        for name, value in scope.get("headers", [])
        if name == b"x-forwarded-for"
    ]
    hops = [hop.strip() for chunk in forwarded for hop in chunk.split(",") if hop.strip()]
    candidate = peer
    for hop in reversed(hops):
        address = _parse(hop)
        if address is None:
            return candidate
        candidate = str(address)
        if not _is_trusted(address, trusted):
            return candidate
    return candidate
