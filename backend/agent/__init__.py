"""
Agent layer for the D2C AI Platform.

This module provides the Full-Funnel Attribution Agent that monitors:
- Meta ad spend → Shopify orders → Razorpay settlements/refunds

The agent runs daily, detects anomalies using hardcoded thresholds,
and uses LLM to generate reasoning and recommendations.
"""

from agent.attribution import (
    analyze_merchant,
    get_lookback_window,
    THRESHOLDS,
)

from agent.tasks import (
    celery_app,
    run_attribution_agent,
)

from agent.scheduler import (
    run_all_merchants,
)

__all__ = [
    "analyze_merchant",
    "get_lookback_window",
    "THRESHOLDS",
    "celery_app",
    "run_attribution_agent",
    "run_all_merchants",
]
