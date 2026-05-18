"""
Chat layer for the D2C AI Platform.

This module provides:
- Tool definitions for querying normalized metrics
- Tool-use loop for LLM-powered chat
- Citation enforcement for data provenance

Usage:
    from chat import chat_with_tools, TOOL_DEFINITIONS
    from chat.citations import validate_full_response
"""

from chat.tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    query_metrics_aggregate,
    query_metrics_timeseries,
    query_metrics_breakdown,
    calculate_roas,
)

from chat.loop import (
    chat_with_tools,
    chat_simple,
    chat_with_context,
    get_default_system_prompt,
)

from chat.citations import (
    extract_citations,
    validate_citation_coverage,
    verify_citations_exist,
    validate_full_response,
    format_citation,
    add_citation_to_claim,
)

__all__ = [
    # Tools
    "TOOL_DEFINITIONS",
    "execute_tool",
    "query_metrics_aggregate",
    "query_metrics_timeseries",
    "query_metrics_breakdown",
    "calculate_roas",
    # Loop
    "chat_with_tools",
    "chat_simple",
    "chat_with_context",
    "get_default_system_prompt",
    # Citations
    "extract_citations",
    "validate_citation_coverage",
    "verify_citations_exist",
    "validate_full_response",
    "format_citation",
    "add_citation_to_claim",
]
