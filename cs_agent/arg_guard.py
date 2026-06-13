"""Deterministic pre-write argument guard (NO LLM) for mutating tool calls.

Fixes the canonical-value subset of the wrong-args failures (e.g. account_class
carrying a "(savings)" qualifier) with rule-based normalization that runs in
microseconds and makes no model call — so it is safe under the 5-min/turn,
10-min/task, 429, and model-lock constraints, and cannot "hallucinate" a wrong
correction the way an LLM verifier can. Fail-open: any error leaves args
untouched. The optional LLM verifier (s6_verify) remains opt-in via S6_VERIFY=1
and is chained AFTER the deterministic pass.
"""

import json
import os

MUTATING_TOOLS = {"call_discoverable_agent_tool"}
# account_class is the bare product name; type belongs in the account_type arg.
_ACCOUNT_CLASS_SUFFIXES = (" (savings)", " (checking)", " (Savings)", " (Checking)")


def _normalize(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            v = v.strip()
            if k == "account_class":
                for suf in _ACCOUNT_CLASS_SUFFIXES:
                    if v.endswith(suf):
                        v = v[: -len(suf)].strip()
        out[k] = v
    return out


def make_before_tool_callback():
    """Always-on deterministic normalizer; chains the LLM S6 verifier only if
    S6_VERIFY=1 (off by default)."""
    llm = None
    if os.environ.get("S6_VERIFY") == "1":
        try:
            from s6_verify import make_before_tool_callback as _mk

            llm = _mk()
        except Exception:
            llm = None

    def before_tool_callback(tool, args, tool_context):
        try:
            if getattr(tool, "name", None) in MUTATING_TOOLS and args.get("arguments"):
                raw = args["arguments"]
                obj = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(obj, dict):
                    norm = _normalize(obj)
                    if norm != obj:
                        args["arguments"] = json.dumps(norm)
        except Exception:
            pass  # fail-open
        return llm(tool, args, tool_context) if llm else None

    return before_tool_callback
