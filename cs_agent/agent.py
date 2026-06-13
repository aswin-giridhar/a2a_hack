"""Rho-Bank customer service agent: policy + env tools + KB search (RAG)."""

import os
from pathlib import Path

from google.adk.agents import LlmAgent

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
and scenario-specific guidance all live in the knowledge base. If a search
comes up empty, rephrase and try again before telling the customer you can't
find the information.
"""

# S6 pre-write arg self-check — OFF unless S6_VERIFY=1 (adds one gemini-3.5-flash
# call per mutating tool call; validate it stays under the 10-min/task cap first).
_before_tool_callback = None
if os.environ.get("S6_VERIFY") == "1":
    from s6_verify import make_before_tool_callback

    _before_tool_callback = make_before_tool_callback()

root_agent = LlmAgent(
    name="cs_agent",
    model=MODEL,
    instruction=POLICY_PATH.read_text() + RAG_GUIDANCE,
    tools=[EnvApiToolset(), kb_search, kb_search_bm25, kb_search_vector],
    before_tool_callback=_before_tool_callback,
)
