"""Infrastructure location for a server/domain ONLY (placeholder).

Returns country/organisation for a domain or IP's hosting
infrastructure, via method="public_lookup". This is NEVER a person's
location: a server's hosting country says nothing about where any
person is, and this module must never be used to place a person.
No live network call is made; values are "not_checked" placeholders
until a real public-lookup adapter supplies them.
"""

import ipaddress
import re

__all__ = ["infrastructure_location"]

_DOMAIN_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")


def infrastructure_location(domain_or_ip: str) -> dict:
    """Placeholder infrastructure location for a domain or IP."""
    value = (domain_or_ip or "").strip().lower()
    kind = "unknown"
    if _DOMAIN_RE.match(value):
        kind = "domain"
    else:
        try:
            ipaddress.ip_address(value)
            kind = "ip_address"
        except ValueError:
            kind = "invalid_input"
    return {
        "input": value,
        "input_kind": kind,
        "scope": "server_or_domain_infrastructure_only",
        "country": "not_checked",
        "organisation": "not_checked",
        "method": "public_lookup",
        "status": "not_checked" if kind in ("domain", "ip_address") else "invalid",
        "note": (
            "Placeholder: no live lookup performed. Infrastructure "
            "location describes a server/domain only and must never "
            "be presented as a person's location."
        ),
    }
