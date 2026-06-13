"""S6 — pre-write argument self-check (grounded, scoped, fail-open).

Research-grounded design (see OPTIMIZATION_NOTES.md §S6):
- Gecko (hf 2602.19218): stateful feedback to refine tool calls on tau2-bench.
- ProgCo (hf 2501.01264): verify NUMERIC args by recomputation, not LLM opinion.
- CorrectBench (hf 2510.16062): ungrounded self-correction can fail AND cost
  latency -> this check is GROUNDED (KB+conversation in the prompt) and SCOPED
  to DB-mutating calls only, and FAIL-OPEN (never blocks a task).
- SPOC (hf 2506.06923): keep it to a single extra pass.

Wiring (off by default): in agent.py, only attach when env S6_VERIFY=1:
    from s6_verify import make_before_tool_callback
    root_agent = LlmAgent(..., before_tool_callback=make_before_tool_callback())

⚠️ MUST VALIDATE before trusting (the model-lock + 10-min/task cap):
  1. Confirm the ADK before_tool_callback signature for the installed version
     (here: (tool, args, tool_context) -> Optional[dict]; return None to
     proceed with possibly-mutated `args`).
  2. Confirm _recent_context() actually pulls conversation text from your
     ToolContext (the one spot that varies by ADK version) — if it returns "",
     the check degrades to args-only and is near-useless, so fix it first.
  3. Re-run train and confirm tasks still finish < 600s (S6 adds one
     gemini-3.5-flash call per mutating tool call).
"""

import json
import os
import sys

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
# Only verify the agent-side DB mutator (where the wrong_args failures live:
# open_bank_account, submit_*_dispute, update_transaction_rewards, ...).
MUTATING_TOOLS = {"call_discoverable_agent_tool"}

_VERIFY_INSTRUCTION = """You are a strict pre-write verifier for a bank CS agent.
A DB-mutating tool call is about to run. Using ONLY the knowledge-base facts and
user-provided values in the context, verify EVERY argument is the exact correct
value. For any NUMERIC argument (amounts, points, counts), RECOMPUTE it step by
step from the KB rules/fee tables and the user's figures — do not trust the
proposed number. Check enum/string values are the exact canonical form (e.g.
account_class is the bare product name, no "(savings)" suffix).

Proposed tool call:
{call}

Relevant context (conversation + KB results so far):
{context}

Respond with ONLY a compact JSON object:
- if every argument is already correct: {{"ok": true}}
- if any argument is wrong: {{"ok": false, "arguments": <the corrected arguments object>}}
No prose, no markdown fences."""


def _recent_context(tool_context, max_chars: int = 6000) -> str:
    """Best-effort: reconstruct recent conversation/KB text from the tool context.

    ⚠️ This is the ADK-version-sensitive spot. Validate it returns real text.
    Fail-open: returns "" if the context shape is unexpected.
    """
    try:
        # ToolContext subclasses ReadonlyContext, which exposes `.session`
        # directly (same property env_toolset.py uses for session.id).
        sess = getattr(tool_context, "session", None)
        if sess is None:
            inv = getattr(tool_context, "_invocation_context", None)
            sess = getattr(inv, "session", None)
        events = getattr(sess, "events", None) or []
        chunks = []
        for ev in events[-30:]:
            content = getattr(ev, "content", None)
            for part in getattr(content, "parts", []) or []:
                txt = getattr(part, "text", None)
                if txt:
                    chunks.append(txt)
                fr = getattr(part, "function_response", None)
                if fr is not None:
                    chunks.append(json.dumps(getattr(fr, "response", ""))[:1500])
        return ("\n".join(chunks))[-max_chars:]
    except Exception:
        return ""


def make_before_tool_callback():
    """Return an ADK before_tool_callback that verifies mutating-call args.

    Returns None always (never short-circuits the tool) — it only mutates the
    `args` dict in place when it finds a correction. Fail-open on any error.
    """
    from google import genai

    client = genai.Client()

    def before_tool_callback(tool, args, tool_context):
        try:
            if getattr(tool, "name", None) not in MUTATING_TOOLS:
                return None
            # call_discoverable_agent_tool args: {agent_tool_name, arguments(JSON str)}
            raw = args.get("arguments")
            if not raw:
                return None
            call_repr = json.dumps(
                {"tool": args.get("agent_tool_name"), "arguments": raw}
            )
            ctx = _recent_context(tool_context)
            if not ctx:
                return None  # no grounding -> skip (ungrounded check is noise)
            prompt = _VERIFY_INSTRUCTION.format(call=call_repr, context=ctx)
            resp = client.models.generate_content(model=MODEL, contents=prompt)
            text = (resp.text or "").strip().strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
            verdict = json.loads(text)
            if verdict.get("ok") is False and "arguments" in verdict:
                corrected = verdict["arguments"]
                # call_discoverable_agent_tool expects arguments as a JSON string
                args["arguments"] = (
                    corrected if isinstance(corrected, str) else json.dumps(corrected)
                )
                print(
                    f"[s6] CORRECTED {args.get('agent_tool_name')}: {raw} -> "
                    f"{args['arguments']}",
                    file=sys.stderr,
                )
            else:
                print(f"[s6] verified ok: {args.get('agent_tool_name')}", file=sys.stderr)
        except Exception as e:
            print(f"[s6] skipped ({type(e).__name__})", file=sys.stderr)  # fail-open
        return None

    return before_tool_callback
