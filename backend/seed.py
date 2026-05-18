#!/usr/bin/env python3
"""
Seed script — creates 3 demo merchants with realistic metrics + agent logs.

Usage:
    cd backend
    source venv/bin/activate
    python seed.py

Creates:
  Merchant 1: Nykaa Fashions Demo     — HEALTHY       (ROAS 3.5, good payments)
  Merchant 2: QuickFashion Co.        — SPEND_WITHOUT_CONVERSION (ROAS 0.8, burning budget)
  Merchant 3: ReturnKing Boutique     — CONVERSION_WITH_RETURNS  (25% refund rate)

Pre-seeds agent_logs with LLM-quality reasoning so the Metrics page works
immediately without needing Celery, Redis, or a real OpenRouter key.

Prints merchant UUIDs at the end — paste into the frontend Navbar input.
Script is idempotent: re-running it replaces data for the fixed UUIDs only.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import AsyncSessionLocal
from models.merchant import Merchant, MerchantConnector
from models.metrics import Metric
from models.agent_log import AgentLog


# ── Fixed merchant UUIDs (paste these into README) ────────────────────────────
M1_ID = uuid.UUID("a1a1a1a1-a1a1-4a1a-8a1a-a1a1a1a1a1a1")  # Nykaa Fashions (healthy)
M2_ID = uuid.UUID("b2b2b2b2-b2b2-4b2b-8b2b-b2b2b2b2b2b2")  # QuickFashion (spend_without_conversion)
M3_ID = uuid.UUID("c3c3c3c3-c3c3-4c3c-8c3c-c3c3c3c3c3c3")  # ReturnKing (conversion_with_returns)

NOW = datetime.now(timezone.utc)


def _days(n_ago_end: int = 1, n_days: int = 7) -> list[date]:
    """Returns a list of dates for the n_days window ending n_ago_end days ago."""
    end = date.today() - timedelta(days=n_ago_end)
    return [end - timedelta(days=i) for i in reversed(range(n_days))]


def _m(val: float) -> Decimal:
    return Decimal(str(val))


# ── Metric row builders ───────────────────────────────────────────────────────

def shopify_rows(merchant_id: uuid.UUID, tag: str, daily: dict, dates: list[date]) -> list[dict]:
    """Build Shopify metric rows for each day. One 'batch order' per day."""
    rows = []
    for d in dates:
        rec_id = f"seed_order_{tag}_{d}"
        base = dict(
            merchant_id=merchant_id,
            source="shopify",
            source_record_id=rec_id,
            date=d,
            fetched_at=NOW,
            raw_data={"seeded": True, "date": str(d)},
        )
        rows += [
            {**base, "id": uuid.uuid4(), "metric_type": "order_revenue",
             "value": _m(daily["order_revenue"]), "currency": "INR",
             "dimensions": {"financial_status": "paid"}},
            {**base, "id": uuid.uuid4(), "metric_type": "order_count",
             "value": _m(daily["order_count"]), "currency": None,
             "dimensions": {"financial_status": "paid"}},
            {**base, "id": uuid.uuid4(), "metric_type": "order_tax",
             "value": _m(daily["order_tax"]), "currency": "INR",
             "dimensions": {}},
            {**base, "id": uuid.uuid4(), "metric_type": "order_shipping",
             "value": _m(daily["order_shipping"]), "currency": "INR",
             "dimensions": {}},
            {**base, "id": uuid.uuid4(), "metric_type": "order_discount",
             "value": _m(daily["order_discount"]), "currency": "INR",
             "dimensions": {"discount_code": f"SAVE{10 + (list(dates).index(d) * 5)}"}},
        ]
        if daily.get("order_refund", 0) > 0:
            rows.append({**base, "id": uuid.uuid4(), "metric_type": "order_refund",
                         "value": _m(daily["order_refund"]), "currency": "INR",
                         "dimensions": {"refund_reason": "customer_request"}})
    return rows


def razorpay_rows(merchant_id: uuid.UUID, tag: str, daily: dict, dates: list[date]) -> list[dict]:
    """Build Razorpay metric rows for each day."""
    rows = []
    for d in dates:
        base = dict(
            merchant_id=merchant_id,
            source="razorpay",
            date=d,
            fetched_at=NOW,
            raw_data={"seeded": True, "date": str(d)},
        )
        rows += [
            {**base, "id": uuid.uuid4(),
             "source_record_id": f"seed_pay_{tag}_{d}",
             "metric_type": "payment_captured",
             "value": _m(daily["payment_captured"]), "currency": "INR",
             "dimensions": {"method": "upi", "status": "captured"}},
            {**base, "id": uuid.uuid4(),
             "source_record_id": f"seed_fail_{tag}_{d}",
             "metric_type": "payment_failed",
             "value": _m(daily["payment_failed"]), "currency": "INR",
             "dimensions": {"method": "card", "status": "failed"}},
            {**base, "id": uuid.uuid4(),
             "source_record_id": f"seed_settle_{tag}_{d}",
             "metric_type": "settlement_amount",
             "value": _m(daily["settlement_amount"]), "currency": "INR",
             "dimensions": {"utr": f"UTR{tag.upper()}{d.strftime('%Y%m%d')}"}},
            {**base, "id": uuid.uuid4(),
             "source_record_id": f"seed_refund_{tag}_{d}",
             "metric_type": "refund_amount",
             "value": _m(daily["refund_amount"]), "currency": "INR",
             "dimensions": {"payment_id": f"pay_{tag}_{d}"}},
        ]
    return rows


def meta_rows(merchant_id: uuid.UUID, tag: str, daily: dict, dates: list[date]) -> list[dict]:
    """Build Meta Ads metric rows for each day."""
    rows = []
    for i, d in enumerate(dates):
        ad_id = f"seed_ad_{tag}_{i + 1:02d}"
        rec_id = f"{ad_id}_{d}"
        base = dict(
            merchant_id=merchant_id,
            source="meta_ads",
            source_record_id=rec_id,
            date=d,
            fetched_at=NOW,
            raw_data={"seeded": True, "date": str(d)},
            dimensions={
                "campaign_id": f"camp_{tag}_001",
                "campaign_name": f"Demo Campaign {tag.title()}",
                "adset_id": f"adset_{tag}_001",
                "adset_name": "Lookalike 3%",
                "ad_id": ad_id,
                "ad_name": f"Ad Creative {i + 1}",
            },
        )
        rows += [
            {**base, "id": uuid.uuid4(), "metric_type": "ad_spend",
             "value": _m(daily["ad_spend"]), "currency": "INR"},
            {**base, "id": uuid.uuid4(), "metric_type": "ad_impressions",
             "value": _m(daily["ad_impressions"]), "currency": None},
            {**base, "id": uuid.uuid4(), "metric_type": "ad_clicks",
             "value": _m(daily["ad_clicks"]), "currency": None},
        ]
        if daily.get("ad_conversions", 0) > 0:
            rows.append({**base, "id": uuid.uuid4(), "metric_type": "ad_conversions",
                         "value": _m(daily["ad_conversions"]), "currency": None})
    return rows


# ── Agent log builders ────────────────────────────────────────────────────────

def agent_log(merchant_id: uuid.UUID, run_ago_days: int, mode: str,
              snapshot: dict, reasoning: str | None, recommendation: str | None,
              confidence: float | None) -> dict:
    return {
        "id": uuid.uuid4(),
        "merchant_id": merchant_id,
        "run_at": datetime.now(timezone.utc) - timedelta(days=run_ago_days),
        "trigger": "scheduled_daily",
        "detection_mode": mode,
        "data_snapshot": snapshot,
        "reasoning": reasoning,
        "recommendation": recommendation,
        "confidence_score": Decimal(str(confidence)) if confidence else None,
        "cited_metric_ids": [],   # empty list is fine for seeded logs
        "status": "completed",
        "error": None,
    }


# ── Main seeding logic ────────────────────────────────────────────────────────

async def seed():
    dates = _days(n_ago_end=1, n_days=7)

    # ── Merchant definitions ──────────────────────────────────────────────────
    merchants = [
        {"id": M1_ID, "name": "Nykaa Fashions Demo", "email": "demo1@nykaa-demo.in"},
        {"id": M2_ID, "name": "QuickFashion Co.",    "email": "demo2@quickfashion-demo.in"},
        {"id": M3_ID, "name": "ReturnKing Boutique", "email": "demo3@returnking-demo.in"},
    ]

    connectors = []
    for m in merchants:
        for ctype in ["shopify", "razorpay", "meta_ads"]:
            connectors.append({
                "id": uuid.uuid4(),
                "merchant_id": m["id"],
                "connector_type": ctype,
                "config": {"note": "demo — no live credentials, data pre-seeded"},
                "is_active": True,
            })

    # ── Metric rows per merchant ──────────────────────────────────────────────

    # M1: Nykaa Fashions — HEALTHY
    # ROAS = 49000/14000 = 3.5  |  capture_rate = 45500/47100 = 0.97  |  refund_rate = 2800/49000 = 0.057
    m1_shopify_daily  = dict(order_revenue=7000, order_count=4, order_tax=630, order_shipping=280, order_discount=350, order_refund=0)
    m1_razorpay_daily = dict(payment_captured=6500, payment_failed=200, settlement_amount=6300, refund_amount=400)
    m1_meta_daily     = dict(ad_spend=2000, ad_impressions=8500, ad_clicks=320, ad_conversions=18)

    # M2: QuickFashion — SPEND_WITHOUT_CONVERSION
    # ROAS = 22400/28000 = 0.8  (< 1.5 threshold)  |  ad_spend 28000 > 5000 threshold
    m2_shopify_daily  = dict(order_revenue=3200, order_count=2, order_tax=288, order_shipping=150, order_discount=120, order_refund=0)
    m2_razorpay_daily = dict(payment_captured=2857, payment_failed=429, settlement_amount=2700, refund_amount=286)
    m2_meta_daily     = dict(ad_spend=4000, ad_impressions=15000, ad_clicks=180, ad_conversions=4)

    # M3: ReturnKing Boutique — CONVERSION_WITH_RETURNS
    # ROAS = 42000/10500 = 4.0 (good) | capture_rate 40000/42700 = 0.94 (good) | refund_rate = 10500/42000 = 0.25 (> 0.20 threshold)
    m3_shopify_daily  = dict(order_revenue=6000, order_count=3, order_tax=540, order_shipping=240, order_discount=300, order_refund=1500)
    m3_razorpay_daily = dict(payment_captured=5714, payment_failed=300, settlement_amount=5500, refund_amount=0)
    m3_meta_daily     = dict(ad_spend=1500, ad_impressions=6200, ad_clicks=290, ad_conversions=12)

    all_metrics = (
        shopify_rows(M1_ID, "m1", m1_shopify_daily, dates) +
        razorpay_rows(M1_ID, "m1", m1_razorpay_daily, dates) +
        meta_rows(M1_ID, "m1", m1_meta_daily, dates) +

        shopify_rows(M2_ID, "m2", m2_shopify_daily, dates) +
        razorpay_rows(M2_ID, "m2", m2_razorpay_daily, dates) +
        meta_rows(M2_ID, "m2", m2_meta_daily, dates) +

        shopify_rows(M3_ID, "m3", m3_shopify_daily, dates) +
        razorpay_rows(M3_ID, "m3", m3_razorpay_daily, dates) +
        meta_rows(M3_ID, "m3", m3_meta_daily, dates)
    )

    # ── Agent logs ─────────────────────────────────────────────────────────────

    # M1 logs — all healthy (shows historical clean runs)
    m1_snap = lambda days_ago: {
        "window": {"start": str(date.today() - timedelta(days=days_ago + 6)), "end": str(date.today() - timedelta(days=days_ago))},
        "ad_spend_inr": 14000.0, "order_revenue_inr": 49000.0, "order_count": 28,
        "captured_payments_inr": 45500.0, "failed_payments_inr": 1400.0, "refund_amount_inr": 2800.0,
        "roas": 3.5, "payment_capture_rate": 0.97, "refund_rate": 0.06,
    }
    m1_logs = [
        agent_log(M1_ID, 1, "healthy", m1_snap(1), None, None, None),
        agent_log(M1_ID, 2, "healthy", m1_snap(2), None, None, None),
        agent_log(M1_ID, 3, "healthy", m1_snap(3), None, None, None),
    ]

    # M2 logs — spend_without_conversion
    m2_snap = lambda days_ago: {
        "window": {"start": str(date.today() - timedelta(days=days_ago + 6)), "end": str(date.today() - timedelta(days=days_ago))},
        "ad_spend_inr": 28000.0, "order_revenue_inr": 22400.0, "order_count": 14,
        "captured_payments_inr": 20000.0, "failed_payments_inr": 3003.0, "refund_amount_inr": 2002.0,
        "roas": 0.8, "payment_capture_rate": 0.87, "refund_rate": 0.09,
    }
    m2_reasoning = (
        "Your ad spend of ₹28,000 over the past 7 days generated only ₹22,400 in order revenue, "
        "producing a ROAS of 0.8x — well below the 1.5x threshold required to cover cost of goods. "
        "For every rupee spent on Meta ads, you're recovering only 80 paise before accounting for "
        "product costs, logistics, and platform fees. At current trajectory, this campaign is "
        "actively destroying margin at ₹5,600 per week."
    )
    m2_recommendation = (
        "• Pause the two highest-spend ad sets immediately and review their cost-per-purchase "
        "in Meta Ads Manager — they are likely broad cold audiences with poor intent signals.\n"
        "• Shift 60% of budget to retargeting (cart abandoners, past purchasers, website visitors "
        "in the last 30 days) which typically deliver 2–4x higher ROAS than cold prospecting.\n"
        "• Audit creative-to-landing-page alignment: if the ad showcases a product that the "
        "landing page doesn't prominently feature, conversion rate collapses regardless of CTR."
    )
    m2_logs = [
        agent_log(M2_ID, 1, "spend_without_conversion", m2_snap(1), m2_reasoning, m2_recommendation, 0.73),
        agent_log(M2_ID, 2, "spend_without_conversion", m2_snap(2), m2_reasoning, m2_recommendation, 0.73),
        agent_log(M2_ID, 3, "healthy", {**m2_snap(3), "roas": 1.8, "ad_spend_inr": 12000.0}, None, None, None),
    ]

    # M3 logs — conversion_with_returns
    m3_snap = lambda days_ago: {
        "window": {"start": str(date.today() - timedelta(days=days_ago + 6)), "end": str(date.today() - timedelta(days=days_ago))},
        "ad_spend_inr": 10500.0, "order_revenue_inr": 42000.0, "order_count": 21,
        "captured_payments_inr": 40000.0, "failed_payments_inr": 2100.0, "refund_amount_inr": 10500.0,
        "roas": 4.0, "payment_capture_rate": 0.95, "refund_rate": 0.25,
    }
    m3_reasoning = (
        "25% of your order revenue over the past 7 days was returned — ₹10,500 in refunds against "
        "₹42,000 in revenue — significantly above the 20% threshold that signals a structural problem. "
        "Each refund carries reverse-logistics overhead (courier + repackaging) that further erodes "
        "net margin beyond the refund amount itself. A 25% refund rate across 21 orders suggests "
        "either an audience-product mismatch (ads reaching shoppers with the wrong intent) or a "
        "product-page accuracy gap (customers receiving something different from expectations)."
    )
    m3_recommendation = (
        "• Pull refund reason data from Shopify Orders → Refunds: if 'not as described' or "
        "'wrong size/fit' dominate, the issue is product page accuracy, not targeting.\n"
        "• Correlate refunds with specific ad sets in Meta Ads Manager — high-return cohorts "
        "typically trace back to broad lookalike audiences or interest-based cold segments.\n"
        "• Add a pre-purchase size guide, detailed measurement chart, or short product demo video "
        "to reduce expectation mismatch, which drives the majority of fashion D2C returns."
    )
    m3_logs = [
        agent_log(M3_ID, 1, "conversion_with_returns", m3_snap(1), m3_reasoning, m3_recommendation, 0.58),
        agent_log(M3_ID, 2, "conversion_with_returns", m3_snap(2), m3_reasoning, m3_recommendation, 0.58),
        agent_log(M3_ID, 3, "conversion_with_returns", {**m3_snap(3), "refund_rate": 0.22}, m3_reasoning, m3_recommendation, 0.53),
    ]

    all_logs = m1_logs + m2_logs + m3_logs

    # ── Write to DB ────────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Wipe existing seeded data for idempotency
            seeded_ids = [M1_ID, M2_ID, M3_ID]
            await session.execute(delete(AgentLog).where(AgentLog.merchant_id.in_(seeded_ids)))
            await session.execute(delete(Metric).where(Metric.merchant_id.in_(seeded_ids)))
            await session.execute(delete(MerchantConnector).where(MerchantConnector.merchant_id.in_(seeded_ids)))
            await session.execute(delete(Merchant).where(Merchant.id.in_(seeded_ids)))

            # Insert merchants first and flush so FKs resolve
            for m in merchants:
                session.add(Merchant(
                    id=m["id"], name=m["name"], email=m["email"],
                    is_active=True,
                    created_at=NOW, updated_at=NOW,
                ))
            await session.flush()

            # Insert connectors
            for c in connectors:
                session.add(MerchantConnector(
                    id=c["id"], merchant_id=c["merchant_id"],
                    connector_type=c["connector_type"], config=c["config"],
                    is_active=True, created_at=NOW, updated_at=NOW,
                ))
            await session.flush()

            # Bulk insert metrics (batched for performance)
            BATCH = 100
            for i in range(0, len(all_metrics), BATCH):
                batch = all_metrics[i:i + BATCH]
                session.add_all([Metric(**row) for row in batch])
            await session.flush()

            # Insert agent logs
            for log in all_logs:
                session.add(AgentLog(**log))

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SEED COMPLETE")
    print("=" * 60)
    print(f"\n  Merchants created : {len(merchants)}")
    print(f"  Connector records : {len(connectors)}")
    print(f"  Metric rows       : {len(all_metrics)}")
    print(f"  Agent log entries : {len(all_logs)}")
    print(f"  Date window       : {dates[0]}  →  {dates[-1]}")
    print("\n" + "-" * 60)
    print("  MERCHANT IDs (paste into frontend Navbar):")
    print("-" * 60)
    print(f"\n  [1] Nykaa Fashions Demo    (HEALTHY)")
    print(f"      {M1_ID}")
    print(f"\n  [2] QuickFashion Co.       (HIGH SPEND / LOW ROAS)")
    print(f"      {M2_ID}")
    print(f"\n  [3] ReturnKing Boutique    (HIGH REFUND RATE)")
    print(f"      {M3_ID}")
    print("\n" + "=" * 60)
    print("\n  The backend server must be running before testing chat.")
    print("  Add your OPENROUTER_API_KEY to .env for the chat layer.\n")


if __name__ == "__main__":
    asyncio.run(seed())
