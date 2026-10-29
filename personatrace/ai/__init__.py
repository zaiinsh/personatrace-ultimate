"""AI layer for PersonaTrace Ultimate (local-first, human-approved).

Default mode "local" is a deterministic template: no network, no key,
no invented content. LLM mode without a key returns status
"not_checked" and never fakes LLM output. Every output carries model,
inputs_summary, and accepted/rejected=None until a human sets it.
"""

from .layer import AILayer

__all__ = ["AILayer"]
