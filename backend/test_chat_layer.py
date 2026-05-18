"""
Test script for Phase 4: Chat Layer

Tests:
1. Tool definitions are valid OpenAI format
2. Citation extraction and validation
3. Tool execution with sample data
"""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from core.database import AsyncSessionLocal, create_tables
from models.merchant import Merchant
from models.metrics import Metric
from models.enums import Source, MetricType
from chat.tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    query_metrics_aggregate,
    query_metrics_timeseries,
    calculate_roas
)
from chat.citations import (
    extract_citations,
    validate_citation_coverage,
    verify_citations_exist,
    format_citation,
    add_citation_to_claim
)


async def setup_test_data():
    """Create test merchant and sample metrics."""
    async with AsyncSessionLocal() as db:
        # Create test merchant
        merchant = Merchant(
            id=uuid4(),
            name="Test Merchant",
            email="test@example.com"
        )
        db.add(merchant)
        await db.commit()
        await db.refresh(merchant)
        
        # Create sample metrics
        test_metrics = [
            # Shopify order revenue (3 days)
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.SHOPIFY.value,
                source_record_id="order_001",
                metric_type=MetricType.ORDER_REVENUE.value,
                value=Decimal("1500.00"),
                currency="INR",
                date=date(2026, 5, 15),
                dimensions={"financial_status": "paid"},
                fetched_at=datetime.now(timezone.utc)
            ),
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.SHOPIFY.value,
                source_record_id="order_002",
                metric_type=MetricType.ORDER_REVENUE.value,
                value=Decimal("2000.00"),
                currency="INR",
                date=date(2026, 5, 16),
                dimensions={"financial_status": "paid"},
                fetched_at=datetime.now(timezone.utc)
            ),
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.SHOPIFY.value,
                source_record_id="order_003",
                metric_type=MetricType.ORDER_REVENUE.value,
                value=Decimal("1800.00"),
                currency="INR",
                date=date(2026, 5, 17),
                dimensions={"financial_status": "paid"},
                fetched_at=datetime.now(timezone.utc)
            ),
            # Meta Ads spend (3 days)
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.META_ADS.value,
                source_record_id="ad_001_2026-05-15",
                metric_type=MetricType.AD_SPEND.value,
                value=Decimal("500.00"),
                currency="INR",
                date=date(2026, 5, 15),
                dimensions={"campaign_id": "camp_001", "campaign_name": "Summer Sale"},
                fetched_at=datetime.now(timezone.utc)
            ),
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.META_ADS.value,
                source_record_id="ad_001_2026-05-16",
                metric_type=MetricType.AD_SPEND.value,
                value=Decimal("600.00"),
                currency="INR",
                date=date(2026, 5, 16),
                dimensions={"campaign_id": "camp_001", "campaign_name": "Summer Sale"},
                fetched_at=datetime.now(timezone.utc)
            ),
            Metric(
                id=uuid4(),
                merchant_id=merchant.id,
                source=Source.META_ADS.value,
                source_record_id="ad_001_2026-05-17",
                metric_type=MetricType.AD_SPEND.value,
                value=Decimal("450.00"),
                currency="INR",
                date=date(2026, 5, 17),
                dimensions={"campaign_id": "camp_001", "campaign_name": "Summer Sale"},
                fetched_at=datetime.now(timezone.utc)
            ),
        ]
        
        for metric in test_metrics:
            db.add(metric)
        
        await db.commit()
        
        print(f"✓ Created test merchant: {merchant.id}")
        print(f"✓ Created {len(test_metrics)} test metrics")
        
        return merchant.id


async def test_tool_definitions():
    """Test 1: Verify tool definitions are valid."""
    print("\n=== Test 1: Tool Definitions ===")
    
    assert len(TOOL_DEFINITIONS) == 4, "Expected 4 tool definitions"
    
    for tool_def in TOOL_DEFINITIONS:
        assert tool_def["type"] == "function", "Tool type must be 'function'"
        assert "function" in tool_def, "Tool must have 'function' key"
        assert "name" in tool_def["function"], "Function must have 'name'"
        assert "description" in tool_def["function"], "Function must have 'description'"
        assert "parameters" in tool_def["function"], "Function must have 'parameters'"
        
        print(f"✓ Tool '{tool_def['function']['name']}' is valid")
    
    print("✓ All tool definitions are valid OpenAI format")


async def test_citations():
    """Test 2: Citation extraction and validation."""
    print("\n=== Test 2: Citations ===")
    
    # Test citation extraction
    text1 = "Revenue was $5,000 [cited: abc-123, def-456]"
    citations1 = extract_citations(text1)
    assert len(citations1) == 2, f"Expected 2 citations, got {len(citations1)}"
    assert "abc-123" in citations1, "Missing citation abc-123"
    print(f"✓ Extracted citations: {citations1}")
    
    # Test citation formatting
    citation_str = format_citation(["uuid-1", "uuid-2"])
    assert citation_str == "[cited: uuid-1, uuid-2]", "Citation formatting failed"
    print(f"✓ Formatted citation: {citation_str}")
    
    # Test adding citation to claim
    claim = "Total revenue was $5,000"
    with_citation = add_citation_to_claim(claim, ["uuid-1"])
    assert "[cited:" in with_citation, "Citation not added"
    print(f"✓ Added citation: {with_citation}")
    
    # Test coverage validation
    good_text = "Revenue was $5,000 [cited: uuid-1] and profit was $2,000 [cited: uuid-2]"
    coverage = validate_citation_coverage(good_text)
    print(f"✓ Coverage validation: {coverage['numbers_found']} numbers, {coverage['citations_found']} citations")
    
    print("✓ Citation utilities work correctly")


async def test_tool_execution(merchant_id):
    """Test 3: Execute tools with test data."""
    print("\n=== Test 3: Tool Execution ===")
    
    async with AsyncSessionLocal() as db:
        # Test 1: Aggregate query
        result1 = await query_metrics_aggregate(
            db=db,
            merchant_id=merchant_id,
            metric_types=[MetricType.ORDER_REVENUE.value],
            aggregation="sum",
            start_date="2026-05-15",
            end_date="2026-05-17",
        )
        
        print(f"✓ Aggregate query result: {result1['result']} {result1['currency']}")
        print(f"  Row count: {result1['row_count']}")
        print(f"  Citations: {len(result1['cited_row_ids'])} row IDs")
        assert result1["result"] == 5300.0, f"Expected 5300.0, got {result1['result']}"
        assert result1["row_count"] == 3, f"Expected 3 rows, got {result1['row_count']}"
        
        # Test 2: Timeseries query
        result2 = await query_metrics_timeseries(
            db=db,
            merchant_id=merchant_id,
            metric_types=[MetricType.AD_SPEND.value],
            aggregation="sum",
            start_date="2026-05-15",
            end_date="2026-05-17",
        )
        
        print(f"✓ Timeseries query result: {len(result2['timeseries'])} data points")
        for point in result2["timeseries"]:
            print(f"  {point['date']}: {point['value']} (citations: {len(point['cited_row_ids'])})")
        assert len(result2["timeseries"]) == 3, f"Expected 3 days, got {len(result2['timeseries'])}"
        
        # Test 3: ROAS calculation
        result3 = await calculate_roas(
            db=db,
            merchant_id=merchant_id,
            start_date="2026-05-15",
            end_date="2026-05-17",
        )
        
        print(f"✓ ROAS calculation result:")
        print(f"  ROAS: {result3['roas']:.2f}")
        print(f"  Revenue: {result3['revenue']} {result3['revenue_currency']}")
        print(f"  Ad Spend: {result3['ad_spend']} {result3['ad_spend_currency']}")
        print(f"  Revenue citations: {len(result3['revenue_cited_row_ids'])}")
        print(f"  Ad Spend citations: {len(result3['ad_spend_cited_row_ids'])}")
        
        expected_roas = 5300.0 / 1550.0  # Total revenue / total ad spend
        assert abs(result3["roas"] - expected_roas) < 0.01, f"ROAS calculation mismatch"
        
        # Test 4: Citation verification
        all_row_ids = result1["cited_row_ids"] + result3["ad_spend_cited_row_ids"]
        verification = await verify_citations_exist(
            cited_row_ids=all_row_ids,
            merchant_id=merchant_id,
            db=db
        )
        
        print(f"✓ Citation verification:")
        print(f"  Found: {verification['found_count']}/{len(all_row_ids)}")
        print(f"  Valid: {verification['valid']}")
        assert verification["valid"], "Citation verification failed"
        
    print("✓ All tool executions successful")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 4: Chat Layer - Test Suite")
    print("=" * 60)
    
    # Test 1: Tool definitions
    await test_tool_definitions()
    
    # Test 2: Citations
    await test_citations()
    
    # Setup test data
    merchant_id = await setup_test_data()
    
    # Test 3: Tool execution
    await test_tool_execution(merchant_id)
    
    print("\n" + "=" * 60)
    print("✓ ALL TESTS PASSED")
    print("=" * 60)
    print("\nPhase 4 Chat Layer is ready for integration!")
    print("\nNext steps:")
    print("1. Integrate with FastAPI routes (Phase 6)")
    print("2. Test with real LLM (requires valid API keys)")
    print("3. Build frontend chat interface (Phase 7)")


if __name__ == "__main__":
    asyncio.run(main())
