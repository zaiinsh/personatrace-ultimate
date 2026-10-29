"""Bio-link domain extraction and (placeholder) domain expansion.

Public data only. ``expand_domain`` performs NO live network calls:
it returns placeholders so unit tests never touch the network. A real
implementation would query Certificate Transparency logs and public DNS
through an adapter; until then every field is honestly "not_checked".
"""

import re
from urllib.parse import urlparse

__all__ = ["extract_domains", "expand_domain"]

_DOMAIN_RE = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")
_DOMAIN_VALID = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")


def _normalise(host: str) -> str | None:
    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if _DOMAIN_VALID.match(host):
        return host
    return None


def extract_domains(bio_links, bio_text: str = "") -> list:
    """Extract deduplicated domains, in first-seen order.

    ``bio_links`` is a list of URLs (or dicts with a "url" key);
    ``bio_text`` is scanned for bare domains, excluding email addresses.
    """
    domains = []
    seen = set()

    def _add(host):
        domain = _normalise(host or "")
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)

    for link in bio_links or []:
        url = link.get("url") if isinstance(link, dict) else link
        if not isinstance(url, str):
            continue
        parsed = urlparse(url if "://" in url else "https://" + url)
        _add(parsed.netloc.split(":")[0].split("@")[-1])
    for match in _DOMAIN_RE.finditer(bio_text or ""):
        start = match.start()
        if start > 0 and bio_text[start - 1] == "@":
            continue  # email address, not a bare domain
        _add(match.group(0))
    return domains


def expand_domain(domain: str) -> dict:
    """Placeholder expansion for a domain (no live network).

    Returns Certificate Transparency / DNS fields as "not_checked"
    with method="public_lookup". This is infrastructure information
    about a domain, never a person's location.
    """
    domain = (domain or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not _DOMAIN_VALID.match(domain):
        return {
            "domain": domain,
            "method": "public_lookup",
            "status": "invalid",
            "ct_log": "not_checked",
            "dns": "not_checked",
            "note": "Not a valid domain; no lookup performed.",
        }
    return {
        "domain": domain,
        "method": "public_lookup",
        "status": "not_checked",
        "ct_log": "not_checked",
        "dns": "not_checked",
        "note": (
            "Placeholder: a live implementation would query public CT logs "
            "and public DNS. No network call is made here."
        ),
    }
