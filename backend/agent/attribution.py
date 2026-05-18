"""
Full-Funnel Attribution Agent

Monitors the complete D2C conversion chain:
Meta ad spend → Shopify orders → Razorpay settlements/refunds

Detection approach:
- Hardcoded thresholds for deterministic anomaly detection
- LLM reasoning only when non-healthy mode detected
- 7-day lookback window ending yesterday (avoids incomplete data)
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.metrics import Metric
from models.enums import Source, MetricType
from core.llm import llm_client
from core.database import AsyncSessionLocal


# Hardcoded thresholds for deterministic detection
# These are v0 defaults — TODO: make per-merchant configurable
THRESHOLDS = {
    "min_ad_spend_inr": 5000,  # Minimum spend to trigger ROAS check
    "bad_roas": 1.5,  # ROAS below this = losing money after COGS
    "min_orders_for_payment_check": 10,  # Minimum orders to check payment rate
    "min_payment_capture_rate": 0.85,  # 85% capture rate minimum (15% failure max)
    "min_orders_for_refund_check": 10,  # Minimum orders to check refund rate
    "max_refund_rate": 0.20,  # 20% refund rate maximum
}


def get_lookback_window() -> tuple[date, date]:
    """
    Returns (start_date, end_date) for the 7-day lookback window.
    
    Window ends yesterday (not today) to avoid:
    - Incomplete same-day data
    - Settlement lag (Razorpay settles 1-2 days after payment)
    
    Returns 7-day range: (yesterday - 6 days, yesterday)
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    return start, end


def _calculate_confidence_score(
    detection_mode: str,
    data_snapshot: dict,
) -> Decimal:
    """
    Calculate confidence score based on threshold distance.
    
    Confidence = how severely the threshold was violated.
    Range: 0.50 (barely past threshold) to 0.99 (far past threshold).
    
    This is NOT an LLM confidence or probabilistic model.
    It's a severity score: how urgent is this alert?
    
    Args:
        detection_mode: The detected failure mode
        data_snapshot: The metrics that triggered detection
    
    Returns:
        Decimal confidence score (0.50 - 0.99)
    """
    if detection_mode == "spend_without_conversion":
        # ROAS severity: lower ROAS = higher confidence
        roas = data_snapshot["roas"]
        threshold = THRESHOLDS["bad_roas"]
        
        # How far below threshold? (0 to threshold range)
        violation = threshold - roas
        severity = min(violation / threshold, 1.0)  # Cap at 1.0
        
        # Map to 0.50-0.99 range
        confidence = 0.50 + (severity * 0.49)
        return Decimal(str(round(confidence, 2)))
    
    elif detection_mode == "orders_without_settlement":
        # Payment capture rate severity: lower rate = higher confidence
        capture_rate = data_snapshot["payment_capture_rate"]
        threshold = THRESHOLDS["min_payment_capture_rate"]
        
        # How far below threshold?
        violation = threshold - capture_rate
        severity = min(violation / threshold, 1.0)
        
        confidence = 0.50 + (severity * 0.49)
        return Decimal(str(round(confidence, 2)))
    
    elif detection_mode == "conversion_with_returns":
        # Refund rate severity: higher refund rate = higher confidence
        refund_rate = data_snapshot["refund_rate"]
        threshold = THRESHOLDS["max_refund_rate"]
        
        # How far above threshold?
        violation = refund_rate - threshold
        # Use 0.5 as the maximum possible refund rate for normalization
        max_violation = 0.5 - threshold
        severity = min(violation / max_violation, 1.0)
        
        confidence = 0.50 + (severity * 0.49)
        return Decimal(str(round(confidence, 2)))
    
    else:
        # Fallback for unknown modes (shouldn't happen)
        return Decimal("0.50")


async def _fetch_metric_sum(
    session: AsyncSession,
    merchant_id: UUID,
    metric_type: MetricType,
    start_date: date,
    end_date: date,
    source: Optional[Source] = None,
) -> tuple[Decimal, list[UUID]]:
    """
    Fetch sum of metric values and list of row IDs for citation.
    
    Returns:
        (total_value, cited_row_ids)
    """
    filters = [
        Metric.merchant_id == merchant_id,
        Metric.metric_type == metric_type,
        Metric.date >= start_date,
        Metric.date <= end_date,
    ]
    
    if source:
        filters.append(Metric.source == source)
    
    stmt = select(
        func.sum(Metric.value).label("total"),
        func.array_agg(Metric.id).label("row_ids"),
    ).where(and_(*filters))
    
    result = await session.execute(stmt)
    row = result.one()
    
    total = row.total if row.total is not None else Decimal(0)
    row_ids = row.row_ids if row.row_ids is not None else []
    
    return total, row_ids


async def _fetch_metric_count(
    session: AsyncSession,
    merchant_id: UUID,
    metric_type: MetricType,
    start_date: date,
    end_date: date,
) -> tuple[int, list[UUID]]:
    """
    Fetch count of metric rows and list of row IDs for citation.
    
    For ORDER_COUNT, the sum of values is the actual order count.
    
    Returns:
        (count, cited_row_ids)
    """
    total, row_ids = await _fetch_metric_sum(
        session, merchant_id, metric_type, start_date, end_date
    )
    return int(total), row_ids


async def analyze_merchant(
    merchant_id: UUID,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """
    Analyze a merchant's full-funnel metrics and detect anomalies.
    
    Detection modes:
    1. spend_without_conversion: High ad spend but low ROAS
    2. orders_without_settlement: High order count but low payment capture
    3. conversion_with_returns: High order count but high refund rate
    4. healthy: All metrics within thresholds
    
    Args:
        merchant_id: Merchant to analyze
        start_date: Start of analysis window (defaults to 7-day lookback)
        end_date: End of analysis window (defaults to yesterday)
    
    Returns:
        dict with:
        - detection_mode: str (one of the 4 modes above)
        - data_snapshot: dict (the raw numbers analyzed)
        - reasoning: str (LLM-generated explanation for all modes)
        - recommendation: str (LLM-generated action items for all modes)
        - cited_metric_ids: list[UUID] (all metric IDs referenced)
        - confidence_score: Decimal | None (0.50-0.99 severity score for non-healthy modes, None for healthy)
          Higher = more severe threshold violation. NOT an LLM probability.
        - status: str ("completed" or "failed")
        - error: str | None (error message if failed)
    """
    # Default to 7-day lookback window
    if start_date is None or end_date is None:
        start_date, end_date = get_lookback_window()
    
    try:
        async with AsyncSessionLocal() as session:
            # Fetch all metrics needed for analysis
            
            # 1. Meta Ads data
            ad_spend, ad_spend_ids = await _fetch_metric_sum(
                session, merchant_id, MetricType.AD_SPEND, start_date, end_date, Source.META_ADS
            )
            
            # 2. Shopify order data
            order_revenue, revenue_ids = await _fetch_metric_sum(
                session, merchant_id, MetricType.ORDER_REVENUE, start_date, end_date, Source.SHOPIFY
            )
            order_count, order_count_ids = await _fetch_metric_count(
                session, merchant_id, MetricType.ORDER_COUNT, start_date, end_date
            )
            
            # 3. Razorpay payment data
            captured_payments, captured_ids = await _fetch_metric_sum(
                session, merchant_id, MetricType.PAYMENT_CAPTURED, start_date, end_date, Source.RAZORPAY
            )
            failed_payments, failed_ids = await _fetch_metric_sum(
                session, merchant_id, MetricType.PAYMENT_FAILED, start_date, end_date, Source.RAZORPAY
            )
            
            # 4. Razorpay refund data
            refund_amount, refund_ids = await _fetch_metric_sum(
                session, merchant_id, MetricType.REFUND_AMOUNT, start_date, end_date, Source.RAZORPAY
            )
            
            # Collect all cited metric IDs
            all_cited_ids = (
                ad_spend_ids + revenue_ids + order_count_ids + 
                captured_ids + failed_ids + refund_ids
            )
            
            # Build data snapshot
            data_snapshot = {
                "window": {"start": str(start_date), "end": str(end_date)},
                "ad_spend_inr": float(ad_spend),
                "order_revenue_inr": float(order_revenue),
                "order_count": order_count,
                "captured_payments_inr": float(captured_payments),
                "failed_payments_inr": float(failed_payments),
                "refund_amount_inr": float(refund_amount),
            }
            
            # Calculate derived metrics
            roas = float(order_revenue / ad_spend) if ad_spend > 0 else 0
            data_snapshot["roas"] = round(roas, 2)
            
            total_payments = captured_payments + failed_payments
            payment_capture_rate = float(captured_payments / total_payments) if total_payments > 0 else 0
            data_snapshot["payment_capture_rate"] = round(payment_capture_rate, 2)
            
            refund_rate = float(refund_amount / order_revenue) if order_revenue > 0 else 0
            data_snapshot["refund_rate"] = round(refund_rate, 2)
            
            # DETECTION LOGIC (hardcoded thresholds)
            detection_mode = "healthy"
            
            # Mode 1: spend_without_conversion
            if (
                ad_spend >= THRESHOLDS["min_ad_spend_inr"]
                and roas < THRESHOLDS["bad_roas"]
            ):
                detection_mode = "spend_without_conversion"
            
            # Mode 2: orders_without_settlement
            elif (
                order_count >= THRESHOLDS["min_orders_for_payment_check"]
                and payment_capture_rate < THRESHOLDS["min_payment_capture_rate"]
            ):
                detection_mode = "orders_without_settlement"
            
            # Mode 3: conversion_with_returns
            elif (
                order_count >= THRESHOLDS["min_orders_for_refund_check"]
                and refund_rate > THRESHOLDS["max_refund_rate"]
            ):
                detection_mode = "conversion_with_returns"
            
            # ALWAYS generate LLM reasoning + recommendation (even for healthy)
            reasoning, recommendation = await _generate_llm_analysis(
                detection_mode, data_snapshot, merchant_id
            )
            
            # Calculate confidence score based on threshold distance (None for healthy)
            confidence_score = None if detection_mode == "healthy" else _calculate_confidence_score(detection_mode, data_snapshot)
            
            return {
                "detection_mode": detection_mode,
                "data_snapshot": data_snapshot,
                "reasoning": reasoning,
                "recommendation": recommendation,
                "cited_metric_ids": all_cited_ids,
                "confidence_score": confidence_score,
                "status": "completed",
                "error": None,
            }
    
    except Exception as e:
        # Log error and return failed status
        return {
            "detection_mode": None,
            "data_snapshot": {},
            "reasoning": None,
            "recommendation": None,
            "cited_metric_ids": [],
            "confidence_score": None,
            "status": "failed",
            "error": str(e),
        }


async def _generate_llm_analysis(
    detection_mode: str,
    data_snapshot: dict,
    merchant_id: UUID,
) -> tuple[str, str]:
    """
    Generate LLM reasoning and recommendation for any detection mode (including healthy).
    
    Args:
        detection_mode: The detected mode (healthy or failure mode)
        data_snapshot: The metrics that triggered detection
        merchant_id: Merchant ID (for context)
    
    Returns:
        (reasoning, recommendation)
    """
    # Build prompt with detected mode and numbers
    if detection_mode == "healthy":
        system_prompt = """You are a D2C business analyst. A merchant's metrics are all within healthy thresholds.

Your job:
1. Summarize the state of the business (2-3 sentences) - acknowledge what's working well
2. Note which metrics have room to grow vs. which are closer to concerning thresholds
3. Provide brief guidance on what to monitor going forward (2-3 bullet points)

Be concise, positive but analytical, and specific. Cite the actual numbers."""
    else:
        system_prompt = """You are a D2C business analyst. A merchant's metrics have triggered an anomaly alert.

Your job:
1. Explain WHY this pattern is concerning (2-3 sentences)
2. Recommend specific, actionable next steps (2-3 bullet points)

Be concise, direct, and specific. Cite the numbers from the data snapshot."""
    
    mode_descriptions = {
        "healthy": "All metrics within healthy thresholds",
        "spend_without_conversion": "High ad spend with low ROAS (losing money on ads)",
        "orders_without_settlement": "High order volume but low payment capture rate (failed payments)",
        "conversion_with_returns": "High order volume but high refund rate (wrong audience or product issues)",
    }
    
    user_prompt = f"""Detection: {mode_descriptions[detection_mode]}

Data (last 7 days):
- Ad Spend: ₹{data_snapshot['ad_spend_inr']:,.2f}
- Order Revenue: ₹{data_snapshot['order_revenue_inr']:,.2f}
- Order Count: {data_snapshot['order_count']}
- ROAS: {data_snapshot['roas']}x
- Payment Capture Rate: {data_snapshot['payment_capture_rate'] * 100:.0f}%
- Refund Rate: {data_snapshot['refund_rate'] * 100:.0f}%
"""
    
    if detection_mode == "healthy":
        user_prompt += f"""
Thresholds (all metrics are within range):
- ROAS: {data_snapshot['roas']}x vs {THRESHOLDS['bad_roas']}x threshold (higher is better)
- Payment Capture Rate: {data_snapshot['payment_capture_rate'] * 100:.0f}% vs {THRESHOLDS['min_payment_capture_rate'] * 100:.0f}% minimum
- Refund Rate: {data_snapshot['refund_rate'] * 100:.0f}% vs {THRESHOLDS['max_refund_rate'] * 100:.0f}% maximum
"""
    else:
        user_prompt += "\nThresholds that were breached:\n"
        if detection_mode == "spend_without_conversion":
            user_prompt += f"- ROAS {data_snapshot['roas']}x < {THRESHOLDS['bad_roas']}x (threshold)\n"
        elif detection_mode == "orders_without_settlement":
            user_prompt += f"- Capture rate {data_snapshot['payment_capture_rate'] * 100:.0f}% < {THRESHOLDS['min_payment_capture_rate'] * 100:.0f}% (threshold)\n"
        elif detection_mode == "conversion_with_returns":
            user_prompt += f"- Refund rate {data_snapshot['refund_rate'] * 100:.0f}% > {THRESHOLDS['max_refund_rate'] * 100:.0f}% (threshold)\n"
    
    user_prompt += "\nProvide your analysis in this format:\n\nREASONING:\n[Your explanation]\n\nRECOMMENDATION:\n[Your action items]"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    
    # Call LLM
    response = await llm_client.chat(messages)
    content = response['choices'][0]['message']['content']
    
    # Parse response (simple split on keywords)
    reasoning = ""
    recommendation = ""
    
    if "REASONING:" in content and "RECOMMENDATION:" in content:
        parts = content.split("RECOMMENDATION:")
        reasoning = parts[0].replace("REASONING:", "").strip()
        recommendation = parts[1].strip()
    else:
        # Fallback if LLM doesn't follow format
        reasoning = content
        recommendation = "Review the metrics and take appropriate action."
    
    return reasoning, recommendation
