"""PersonaTrace adapters package: free, gated and registry exports."""

from .base import (
    AdapterResult,
    BaseAdapter,
    Edge,
    Evidence,
    Investigation,
    Profile,
    confidence_band,
    is_demo_mode,
)
from .free import FREE_ADAPTERS
from .gated import GATED_ADAPTERS, LicensedAggregatorAdapter
from .mock_data import DEMO_SEED, demo_profiles
from .registry import ADAPTERS, available_adapters
from .site_lists import CLOSED_PLATFORMS, SITE_LISTS, build_site_urls, site_url

__all__ = [
    "AdapterResult",
    "BaseAdapter",
    "Edge",
    "Evidence",
    "Investigation",
    "Profile",
    "confidence_band",
    "is_demo_mode",
    "FREE_ADAPTERS",
    "GATED_ADAPTERS",
    "LicensedAggregatorAdapter",
    "DEMO_SEED",
    "demo_profiles",
    "ADAPTERS",
    "available_adapters",
    "CLOSED_PLATFORMS",
    "SITE_LISTS",
    "build_site_urls",
    "site_url",
]
