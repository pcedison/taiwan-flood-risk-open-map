"""Shared client-signal resolution for rate limiting.

Proxy-chain headers such as ``X-Forwarded-For`` are client-forgeable on the
left: each proxy appends the peer address it actually saw to the right, so
the only trustworthy entry is the right-most hop that is not one of the
proxies we deploy behind. Loopback, private, and link-local addresses are
always treated as our own proxy hops; additional operator-controlled ranges
(for example a CDN egress block) can be supplied as trusted CIDRs.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

from fastapi import Request


def resolve_client_signal(
    request: Request,
    configured_header: str | None,
    trusted_proxy_cidrs: Sequence[str] = (),
) -> str:
    if configured_header:
        header_value = request.headers.get(configured_header)
        if header_value:
            signal = _rightmost_untrusted_hop(header_value, trusted_proxy_cidrs)
            if signal:
                return signal
    if request.client is None:
        return "unknown-client"
    return request.client.host


# Ranges a reverse proxy or ingress realistically lives in. Deliberately an
# explicit list rather than ipaddress.is_private, which also matches
# documentation/TEST-NET ranges that are not proxy infrastructure.
_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "127.0.0.0/8",  # loopback
        "10.0.0.0/8",  # RFC1918
        "172.16.0.0/12",  # RFC1918
        "192.168.0.0/16",  # RFC1918
        "169.254.0.0/16",  # link-local
        "100.64.0.0/10",  # CGNAT, used by some cluster networks
        "::1/128",  # loopback
        "fc00::/7",  # unique local
        "fe80::/10",  # link-local
    )
)


def _rightmost_untrusted_hop(
    header_value: str,
    trusted_proxy_cidrs: Sequence[str],
) -> str | None:
    hops = [hop.strip() for hop in header_value.split(",")]
    hops = [hop for hop in hops if hop]
    if not hops:
        return None
    trusted_networks = _parse_networks(trusted_proxy_cidrs)
    for hop in reversed(hops):
        address = _parse_address(hop)
        if address is None:
            # Non-IP token reported by the nearest proxy; still the most
            # trustworthy entry available.
            return hop
        if any(address in network for network in _PROXY_NETWORKS):
            continue
        if any(address in network for network in trusted_networks):
            continue
        return hop
    # Every hop is a proxy-range address: a fully private chain means the
    # left-most entry is the original client on the local network.
    return hops[0]


def _parse_networks(
    trusted_proxy_cidrs: Sequence[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in trusted_proxy_cidrs:
        candidate = cidr.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    return networks


def _parse_address(hop: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = hop
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1:
        host, _, port = candidate.partition(":")
        if port.isdigit():
            candidate = host
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None
