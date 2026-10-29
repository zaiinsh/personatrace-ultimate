"""AI layer: local deterministic templates, or a real LLM (key-gated).

- mode="local" (default): deterministic template summarisation,
  model="local-template-v1", no network, no key required.
- mode="llm" without an API key: every method returns
  status="not_checked" with a prompt to add a key in Settings > API
  Keys. It NEVER fabricates LLM output.
- mode="llm" with a key: a REAL OpenAI-compatible chat-completions
  call is made (single POST, 30s timeout, no retry on 429) to
  base_url (default https://api.openai.com/v1, or env
  PERSONATRACE_LLM_BASE_URL / keys "llm_base_url", or a
  user-supplied OpenAI-compatible endpoint) with model
  (default gpt-4o-mini, or env PERSONATRACE_LLM_MODEL / keys
  "llm_model"). The key is sent only to that endpoint, never echoed
  in any output. Only public case data already collected is sent;
  no private data is ever sent to an LLM. A failed call is degraded,
  never a fabricated summary.

Every output dict carries: model, inputs_summary, and
accepted/rejected=None until a human reviewer sets it (log the
decision via storage.log_audit). ``labelled`` is True for local
template output (it is labelled as a template, not as LLM output).
"""

__all__ = ["AILayer"]

_LOCAL_MODEL = "local-template-v1"
_KEY_PROMPT = "Add an API key in Settings > API Keys to enable LLM mode."


def _get(obj, field, default=None):
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _inputs_summary(profiles, edges):
    platforms = sorted({_get(p, "platform", "") for p in (profiles or []) if _get(p, "platform", "")})
    return {
        "profile_count": len(profiles or []),
        "edge_count": len(edges or []),
        "platforms": platforms,
    }


class AILayer:
    """Local-template or LLM AI layer (see module docstring)."""

    def __init__(self, mode: str = "local", api_key=None, base_url=None, model=None, keys: dict | None = None):
        # v2.0: mode="local_model" = the investigator's own local model
        # (e.g. Ollama on http://localhost:11434, or any OpenAI-compatible
        # local server). No cloud key is needed, and when the endpoint
        # is localhost the case data never leaves the machine.
        if mode not in ("local", "llm", "local_model"):
            raise ValueError(f"unknown AI mode: {mode!r} (expected 'local', 'llm' or 'local_model')")
        import os

        keys = keys or {}
        self.mode = mode
        self.api_key = (
            api_key
            or keys.get("llm_api_key")
            or keys.get("openai_api_key")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("PERSONATRACE_LLM_KEY")
        )
        self.base_url = (
            base_url
            or keys.get("llm_base_url")
            or os.environ.get("PERSONATRACE_LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = (
            model
            or keys.get("llm_model")
            or os.environ.get("PERSONATRACE_LLM_MODEL")
            or "gpt-4o-mini"
        )
        self.local_model_url = (
            keys.get("local_model_url")
            or os.environ.get("PERSONATRACE_LOCAL_MODEL_URL")
            or "http://localhost:11434"
        ).rstrip("/")
        self.local_model_name = (
            keys.get("local_model_name")
            or os.environ.get("PERSONATRACE_LOCAL_MODEL_NAME")
            or "llama3"
        )

    def local_model_summary(self, prompt: str) -> dict:
        """Call the investigator's local model (Ollama generate API, or
        an OpenAI-compatible local chat endpoint). No key, no cloud."""
        import json as _json, urllib.request as _req, urllib.error as _err
        # Try OpenAI-compatible chat completions first (llama.cpp, LM Studio).
        try:
            data = _json.dumps({"model": self.local_model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}).encode()
            request = _req.Request(self.local_model_url + "/v1/chat/completions", data=data, headers={"Content-Type": "application/json"})
            with _req.urlopen(request, timeout=60) as resp:
                out = _json.loads(resp.read().decode())
                text = out["choices"][0]["message"]["content"]
                return {"status": "ok", "model": self.local_model_name, "text": text, "endpoint": self.local_model_url, "note": "Local model output — case data stayed on this machine when the endpoint is localhost."}
        except Exception:
            pass
        try:
            data = _json.dumps({"model": self.local_model_name, "prompt": prompt, "stream": False}).encode()
            request = _req.Request(self.local_model_url + "/api/generate", data=data, headers={"Content-Type": "application/json"})
            with _req.urlopen(request, timeout=60) as resp:
                out = _json.loads(resp.read().decode())
                return {"status": "ok", "model": self.local_model_name, "text": out.get("response"), "endpoint": self.local_model_url, "note": "Local model output — case data stayed on this machine when the endpoint is localhost."}
        except Exception as exc:
            return {"status": "not_checked", "model": self.local_model_name, "text": None, "reason": f"Local model not reachable at {self.local_model_url}: {exc}. Start your local model (e.g. Ollama) and set PERSONATRACE_LOCAL_MODEL_URL."}

    # -- internal -----------------------------------------------------
    def _not_checked(self, inputs_summary, action: str) -> dict:
        reason = _KEY_PROMPT if not self.api_key else "LLM provider not configured in this build."
        return {
            "text": None,
            "model": "llm",
            "inputs_summary": inputs_summary,
            "labelled": True,
            "accepted": None,
            "rejected": None,
            "status": "not_checked",
            "action": action,
            "message": reason,
        }

    def _call_llm(self, prompt: str, inputs_summary, action: str) -> dict:
        """One real OpenAI-compatible chat-completions call, or degraded."""
        if not self.api_key:
            return self._not_checked(inputs_summary, action)
        import json as _json
        import urllib.error as _err
        import urllib.request as _req

        payload = _json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an OSINT analyst assistant. Summarise only the public case data given. Never invent facts, never claim an identity is confirmed, and flag uncertainty explicitly."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        request = _req.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with _req.urlopen(request, timeout=30) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if not text:
                raise ValueError("empty LLM response")
            return {
                "text": text,
                "model": self.model,
                "inputs_summary": inputs_summary,
                "labelled": True,
                "accepted": None,
                "rejected": None,
                "status": "ok",
                "action": action,
            }
        except _err.HTTPError as exc:
            return {
                "text": None, "model": self.model, "inputs_summary": inputs_summary,
                "labelled": True, "accepted": None, "rejected": None,
                "status": "degraded", "action": action,
                "message": f"LLM call failed (HTTP {exc.code}) — not retried, no output fabricated.",
            }
        except Exception as exc:
            return {
                "text": None, "model": self.model, "inputs_summary": inputs_summary,
                "labelled": True, "accepted": None, "rejected": None,
                "status": "degraded", "action": action,
                "message": f"LLM call failed ({exc}) — no output fabricated.",
            }

    def _base(self, text, inputs_summary, **extra):
        result = {
            "text": text,
            "model": _LOCAL_MODEL,
            "inputs_summary": inputs_summary,
            "labelled": True,
            "accepted": None,
            "rejected": None,
            "status": "ok",
        }
        result.update(extra)
        return result

    # -- public -------------------------------------------------------
    def summarise(self, profiles, edges) -> dict:
        """Deterministic template summary of profiles + edges."""
        summary = _inputs_summary(profiles, edges)
        if self.mode == "llm":
            usernames = [_get(p, "username", "") for p in (profiles or [])]
            prompt = (
                "Summarise this public OSINT case in plain language, with "
                "uncertainty flagged. Profiles: " + ", ".join(usernames)
                + f". Platforms: {', '.join(summary['platforms'])}. "
                f"Edges: {len(edges or [])}. Do not claim any identity is confirmed."
            )
            return self._call_llm(prompt, summary, "summarise")
        usernames = [_get(p, "username", "") for p in (profiles or [])]
        edge_kinds = sorted({_get(e, "kind", "") for e in (edges or []) if _get(e, "kind", "")})
        text = (
            f"Template summary ({_LOCAL_MODEL}): {len(profiles or [])} public profile(s) "
            f"across {len(summary['platforms'])} platform(s) "
            f"({', '.join(summary['platforms']) or 'none'}), "
            f"connected by {len(edges or [])} edge(s)"
            + (f" of kind(s): {', '.join(edge_kinds)}." if edge_kinds else ".")
            + f" Seed-linked usernames: {', '.join(usernames) if usernames else 'none'}."
            + " This is a deterministic template summary, not LLM output;"
            + " every fact must be checked against its source evidence."
        )
        return self._base(text, summary)

    def translate(self, text: str, target: str) -> dict:
        """Local mode preserves the original; no translation is faked."""
        summary = {"source_chars": len(text or ""), "target": target}
        if self.mode == "llm":
            result = self._call_llm(
                f"Translate this public text to {target}, preserving meaning. "
                f"Return only the translation. Text: {text or ''}",
                summary, "translate")
            if result.get("status") == "ok":
                result["original_text"] = text or ""
                result["translated_text"] = result.get("text")
            return result
        return self._base(
            text or "",
            summary,
            original_text=text or "",
            translated_text=None,
            target=target,
            note=(
                "Local template mode performs no translation. Original "
                "text is preserved verbatim; translated_text is None "
                "until a real translation step supplies it."
            ),
        )

    def draft_report(self, inv) -> dict:
        """Draft a report outline from an investigation (template)."""
        profiles = _get(inv, "profiles", []) or []
        edges = _get(inv, "edges", []) or []
        summary = _inputs_summary(profiles, edges)
        summary["case_id"] = _get(inv, "case_id", "")
        summary["seed"] = _get(inv, "seed", "")
        if self.mode == "llm":
            return self._call_llm(
                f"Draft a report outline for case {summary['case_id']} (seed {summary['seed']}) "
                f"with {len(profiles)} public profile(s) and {len(edges)} edge(s). "
                "Sections only, no invented facts, human review required.",
                summary, "draft_report")
        text = (
            f"Template report draft ({_LOCAL_MODEL}) for case "
            f"{summary['case_id']} (seed {summary['seed']}): "
            f"{len(profiles)} profile(s), {len(edges)} edge(s), "
            f"{len(_get(inv, 'possible_matches', []) or [])} possible-match entr(ies), "
            f"{len(_get(inv, 'alerts', []) or [])} alert(s). "
            "Sections: seed profile, linked profiles, evidence with "
            "provenance, possible matches awaiting human review, alerts, "
            "audit log. Human review required before any conclusion is used."
        )
        return self._base(text, summary)
