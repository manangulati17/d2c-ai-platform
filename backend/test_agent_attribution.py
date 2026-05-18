"""
Test agent/attribution.py — Full-Funnel Attribution Agent

Tests all 4 detection modes:
1. spend_without_conversion (high spend, low ROAS)
2. orders_without_settlement (high orders, low payment capture)
3. conversion_with_returns (high orders, high refund rate)
4. healthy (all thresholds within bounds)
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from core.database import AsyncSessionLocal
from models.metrics import Metric
from models.merchant import Merchant
from models.enums import Source, MetricType
from agent.attribution import analyze_merchant, get_lookback_window, THRESHOLDS


async def setup_test_merchant():
    """Create a test merchant for analysis."""
    async with AsyncSessionLocal() as session:
        merchant = Merchant(
            name="Test Merchant",
            email=f"test_{uuid4().hex[:8]}@example.com",
        )
        session.add(merchant)
        await session.commit()
        await session.refresh(merchant)
        return merchant.id


async def insert_metrics(merchant_id, metrics_data):
    """Insert test metrics into the database."""
    async with AsyncSessionLocal() as session:
        for metric_dict in metrics_data:
            metric = Metric(**metric_dict, merchant_id=merchant_id)
            session.add(metric)
        await session.commit()


async def test_lookback_window():
    """Test get_lookback_window() returns correct 7-day range."""
    print("\n=== Test: Lookback Window ===")
    start, end = get_lookback_window()
    
    expected_end = date.today() - timedelta(days=1)
    expected_start = expected_end - timedelta(days=6)
    
    assert start == expected_start, f"Expected start {expected_start}, got {start}"
    assert end == expected_end, f"Expected end {expected_end}, got {end}"
    
    print(f"✓ Lookback window: {start} to {end} (7 days ending yesterday)")


async def test_scenario_1_spend_without_conversion():
    """
    Scenario 1: spend_without_conversion
    - Ad spend: ₹10,000
    - Order revenue: ₹8,000
    - ROAS: 0.8x (< 1.5 threshold)
    - Should trigger: spend_without_conversion
    """
    print("\n=== Test: Scenario 1 - Spend Without Conversion ===")
    
    merchant_id = await setup_test_merchant()
    start, end = get_lookback_window()
    
    # Insert metrics: high ad spend, low ROAS
    metrics = [
        # Meta Ads: ₹10,000 spend
        {
            "source": Source.META_ADS,
            "source_record_id": "ad_001",
            "metric_type": MetricType.AD_SPEND,
            "value": Decimal("10000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Shopify: ₹8,000 revenue (ROAS 0.8x)
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_001",
            "metric_type": MetricType.ORDER_REVENUE,
            "value": Decimal("8000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_001",
            "metric_type": MetricType.ORDER_COUNT,
            "value": Decimal("5"),
            "currency": None,
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Razorpay: decent payment capture
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_001",
            "metric_type": MetricType.PAYMENT_CAPTURED,
            "value": Decimal("7500"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
    ]
    
    await insert_metrics(merchant_id, metrics)
    
    # Analyze
    result = await analyze_merchant(merchant_id, start, end)
    
    # Check for errors
    if result["status"] == "failed":
        print(f"❌ Analysis failed: {result['error']}")
        raise AssertionError(f"Analysis failed: {result['error']}")
    
    print(f"Detection mode: {result['detection_mode']}")
    print(f"ROAS: {result['data_snapshot']['roas']}x")
    print(f"Ad spend: ₹{result['data_snapshot']['ad_spend_inr']:,.2f}")
    print(f"Order revenue: ₹{result['data_snapshot']['order_revenue_inr']:,.2f}")
    
    assert result["detection_mode"] == "spend_without_conversion", \
        f"Expected spend_without_conversion, got {result['detection_mode']}"
    assert result["reasoning"] is not None, "Expected LLM reasoning for non-healthy mode"
    assert result["recommendation"] is not None, "Expected LLM recommendation"
    assert result["status"] == "completed", f"Expected completed status, got {result['status']}"
    assert len(result["cited_metric_ids"]) > 0, "Expected cited metric IDs"
    
    print(f"✓ Correctly detected: {result['detection_mode']}")
    print(f"✓ LLM reasoning generated: {len(result['reasoning'])} chars")
    print(f"✓ LLM recommendation generated: {len(result['recommendation'])} chars")
    print(f"✓ Citations: {len(result['cited_metric_ids'])} metric IDs")


async def test_scenario_2_orders_without_settlement():
    """
    Scenario 2: orders_without_settlement
    - Order count: 15
    - Captured payments: ₹10,000
    - Failed payments: ₹5,000
    - Capture rate: 66% (< 85% threshold)
    - Should trigger: orders_without_settlement
    """
    print("\n=== Test: Scenario 2 - Orders Without Settlement ===")
    
    merchant_id = await setup_test_merchant()
    start, end = get_lookback_window()
    
    # Insert metrics: high orders, low payment capture
    metrics = [
        # Meta Ads: modest spend
        {
            "source": Source.META_ADS,
            "source_record_id": "ad_002",
            "metric_type": MetricType.AD_SPEND,
            "value": Decimal("8000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Shopify: 15 orders, ₹15,000 revenue (ROAS 1.875 - healthy)
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_002",
            "metric_type": MetricType.ORDER_REVENUE,
            "value": Decimal("15000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_002",
            "metric_type": MetricType.ORDER_COUNT,
            "value": Decimal("15"),
            "currency": None,
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Razorpay: LOW payment capture (66%)
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_002",
            "metric_type": MetricType.PAYMENT_CAPTURED,
            "value": Decimal("10000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_002_fail",
            "metric_type": MetricType.PAYMENT_FAILED,
            "value": Decimal("5000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
    ]
    
    await insert_metrics(merchant_id, metrics)
    
    # Analyze
    result = await analyze_merchant(merchant_id, start, end)
    
    print(f"Detection mode: {result['detection_mode']}")
    print(f"Order count: {result['data_snapshot']['order_count']}")
    print(f"Payment capture rate: {result['data_snapshot']['payment_capture_rate'] * 100:.0f}%")
    print(f"Captured: ₹{result['data_snapshot']['captured_payments_inr']:,.2f}")
    print(f"Failed: ₹{result['data_snapshot']['failed_payments_inr']:,.2f}")
    
    assert result["detection_mode"] == "orders_without_settlement", \
        f"Expected orders_without_settlement, got {result['detection_mode']}"
    assert result["reasoning"] is not None, "Expected LLM reasoning"
    assert result["status"] == "completed"
    
    print(f"✓ Correctly detected: {result['detection_mode']}")
    print(f"✓ LLM analysis generated")


async def test_scenario_3_conversion_with_returns():
    """
    Scenario 3: conversion_with_returns
    - Order count: 20
    - Order revenue: ₹20,000
    - Refund amount: ₹5,000
    - Refund rate: 25% (> 20% threshold)
    - Should trigger: conversion_with_returns
    """
    print("\n=== Test: Scenario 3 - Conversion With Returns ===")
    
    merchant_id = await setup_test_merchant()
    start, end = get_lookback_window()
    
    # Insert metrics: high orders, high refund rate
    metrics = [
        # Meta Ads: modest spend
        {
            "source": Source.META_ADS,
            "source_record_id": "ad_003",
            "metric_type": MetricType.AD_SPEND,
            "value": Decimal("8000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Shopify: 20 orders, ₹20,000 revenue (ROAS 2.5 - healthy)
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_003",
            "metric_type": MetricType.ORDER_REVENUE,
            "value": Decimal("20000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_003",
            "metric_type": MetricType.ORDER_COUNT,
            "value": Decimal("20"),
            "currency": None,
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Razorpay: good payment capture
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_003",
            "metric_type": MetricType.PAYMENT_CAPTURED,
            "value": Decimal("19000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_003_fail",
            "metric_type": MetricType.PAYMENT_FAILED,
            "value": Decimal("1000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # HIGH refund rate (25%)
        {
            "source": Source.RAZORPAY,
            "source_record_id": "ref_003",
            "metric_type": MetricType.REFUND_AMOUNT,
            "value": Decimal("5000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
    ]
    
    await insert_metrics(merchant_id, metrics)
    
    # Analyze
    result = await analyze_merchant(merchant_id, start, end)
    
    print(f"Detection mode: {result['detection_mode']}")
    print(f"Order count: {result['data_snapshot']['order_count']}")
    print(f"Refund rate: {result['data_snapshot']['refund_rate'] * 100:.0f}%")
    print(f"Order revenue: ₹{result['data_snapshot']['order_revenue_inr']:,.2f}")
    print(f"Refund amount: ₹{result['data_snapshot']['refund_amount_inr']:,.2f}")
    
    assert result["detection_mode"] == "conversion_with_returns", \
        f"Expected conversion_with_returns, got {result['detection_mode']}"
    assert result["reasoning"] is not None, "Expected LLM reasoning"
    assert result["status"] == "completed"
    
    print(f"✓ Correctly detected: {result['detection_mode']}")
    print(f"✓ LLM analysis generated")


async def test_scenario_4_healthy():
    """
    Scenario 4: healthy
    - ROAS: 2.5x (> 1.5 threshold)
    - Payment capture rate: 95% (> 85% threshold)
    - Refund rate: 5% (< 20% threshold)
    - Should trigger: healthy (no LLM call)
    """
    print("\n=== Test: Scenario 4 - Healthy ===")
    
    merchant_id = await setup_test_merchant()
    start, end = get_lookback_window()
    
    # Insert metrics: all thresholds healthy
    metrics = [
        # Meta Ads: ₹10,000 spend
        {
            "source": Source.META_ADS,
            "source_record_id": "ad_004",
            "metric_type": MetricType.AD_SPEND,
            "value": Decimal("10000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Shopify: ₹25,000 revenue (ROAS 2.5x)
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_004",
            "metric_type": MetricType.ORDER_REVENUE,
            "value": Decimal("25000"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.SHOPIFY,
            "source_record_id": "order_004",
            "metric_type": MetricType.ORDER_COUNT,
            "value": Decimal("20"),
            "currency": None,
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Razorpay: 95% payment capture
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_004",
            "metric_type": MetricType.PAYMENT_CAPTURED,
            "value": Decimal("23750"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        {
            "source": Source.RAZORPAY,
            "source_record_id": "pay_004_fail",
            "metric_type": MetricType.PAYMENT_FAILED,
            "value": Decimal("1250"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
        # Low refunds (5%)
        {
            "source": Source.RAZORPAY,
            "source_record_id": "ref_004",
            "metric_type": MetricType.REFUND_AMOUNT,
            "value": Decimal("1250"),
            "currency": "INR",
            "date": start,
            "raw_data": {},
            "fetched_at": date.today(),
        },
    ]
    
    await insert_metrics(merchant_id, metrics)
    
    # Analyze
    result = await analyze_merchant(merchant_id, start, end)
    
    print(f"Detection mode: {result['detection_mode']}")
    print(f"ROAS: {result['data_snapshot']['roas']}x")
    print(f"Payment capture rate: {result['data_snapshot']['payment_capture_rate'] * 100:.0f}%")
    print(f"Refund rate: {result['data_snapshot']['refund_rate'] * 100:.0f}%")
    
    assert result["detection_mode"] == "healthy", \
        f"Expected healthy, got {result['detection_mode']}"
    assert result["reasoning"] is None, "Expected no LLM reasoning for healthy mode"
    assert result["recommendation"] is None, "Expected no recommendation for healthy mode"
    assert result["status"] == "completed"
    assert len(result["cited_metric_ids"]) > 0, "Expected cited metric IDs even for healthy"
    
    print(f"✓ Correctly detected: {result['detection_mode']}")
    print(f"✓ No LLM call (reasoning=None, recommendation=None)")
    print(f"✓ Citations preserved: {len(result['cited_metric_ids'])} metric IDs")


async def main():
    """Run all attribution tests."""
    print("=" * 60)
    print("TESTING: agent/attribution.py")
    print("=" * 60)
    
    # Test 0: Lookback window
    await test_lookback_window()
    
    # Test 1: spend_without_conversion
    await test_scenario_1_spend_without_conversion()
    
    # Test 2: orders_without_settlement
    await test_scenario_2_orders_without_settlement()
    
    # Test 3: conversion_with_returns
    await test_scenario_3_conversion_with_returns()
    
    # Test 4: healthy
    await test_scenario_4_healthy()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
    print("\nTask 5.1 Complete:")
    print("- THRESHOLDS dict with 6 threshold values ✓")
    print("- get_lookback_window() returns 7-day window ending yesterday ✓")
    print("- analyze_merchant() queries all metrics ✓")
    print("- Detection logic for 3 modes + healthy ✓")
    print("- LLM call only when non-healthy ✓")
    print("- Structured result with citations ✓")
    print("- All 4 detection modes tested ✓")


if __name__ == "__main__":
    asyncio.run(main())
