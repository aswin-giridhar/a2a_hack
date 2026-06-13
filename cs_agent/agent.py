"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

from arg_guard import make_before_tool_callback
from compute_tool import compute
from env_toolset import EnvApiToolset
from rag_tools import kb_search, kb_search_bm25, kb_search_vector

MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
POLICY_PATH = Path(os.environ.get("KB_POLICY_PATH", "/app/kb/policy.md"))

RAG_GUIDANCE = """

## Knowledge Base Access

You do NOT have the knowledge base inlined. Before answering policy questions
or performing scenario-specific procedures, search the knowledge base:
- kb_search(query): PRIMARY tool — hybrid keyword + semantic search, fused and
  reranked. Use this for nearly everything; it returns the most relevant docs.
- kb_search_bm25(query): keyword-only fallback for an exact term/ID/tool name.
- kb_search_vector(query): semantic-only fallback.

Search before you act; procedures, eligibility rules, internal tool names,
and scenario-specific guidance all live in the knowledge base. Prefer ONE
comprehensive kb_search per question (include all relevant keywords) rather
than many small searches — extra round-trips add latency toward the turn/task
time limits. If a search comes up empty, rephrase and try again before telling
the customer you can't find the information.

## Exact Calculations

For ANY money, fee, refund, reward-point, percentage, or total figure, call
compute(expression) to get the exact value — do NOT do arithmetic in your head,
as small slips produce wrong tool arguments. Example: compute("(27.00 + 8.00) * 0.5").
"""

# Deterministic pre-write arg guard (always on; no LLM, no latency/429/model-lock
# impact). The optional LLM verifier (s6_verify) is chained only if S6_VERIFY=1.
_before_tool_callback = make_before_tool_callback()

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text() + RAG_GUIDANCE,
    tools=[EnvApiToolset(), kb_search, kb_search_bm25, kb_search_vector, compute],
    before_tool_callback=_before_tool_callback,
)
