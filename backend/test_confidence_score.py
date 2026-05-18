"""
Test confidence score calculation for agent attribution.

Tests the threshold-distance heuristic:
- Higher severity violations → higher confidence
- Confidence range: 0.50 (barely past threshold) to 0.99 (far past)
"""

from decimal import Decimal
from agent.attribution import _calculate_confidence_score, THRESHOLDS


def test_confidence_spend_without_conversion():
    """Test confidence calculation for spend_without_conversion mode."""
    print("\n=== Test: Confidence for Spend Without Conversion ===")
    
    # Scenario 1: ROAS = 0.3 (very bad, 80% below threshold of 1.5)
    data_snapshot_severe = {
        "roas": 0.3,
        "ad_spend_inr": 10000,
        "order_revenue_inr": 3000,
    }
    confidence_severe = _calculate_confidence_score("spend_without_conversion", data_snapshot_severe)
    print(f"ROAS 0.3 (threshold 1.5) → Confidence: {confidence_severe}")
    assert confidence_severe >= Decimal("0.85"), f"Severe violation should have high confidence, got {confidence_severe}"
    
    # Scenario 2: ROAS = 1.4 (barely below threshold of 1.5)
    data_snapshot_mild = {
        "roas": 1.4,
        "ad_spend_inr": 10000,
        "order_revenue_inr": 14000,
    }
    confidence_mild = _calculate_confidence_score("spend_without_conversion", data_snapshot_mild)
    print(f"ROAS 1.4 (threshold 1.5) → Confidence: {confidence_mild}")
    assert confidence_mild <= Decimal("0.60"), f"Mild violation should have low confidence, got {confidence_mild}"
    
    # Scenario 3: ROAS = 0.0 (no revenue at all)
    data_snapshot_zero = {
        "roas": 0.0,
        "ad_spend_inr": 10000,
        "order_revenue_inr": 0,
    }
    confidence_zero = _calculate_confidence_score("spend_without_conversion", data_snapshot_zero)
    print(f"ROAS 0.0 (threshold 1.5) → Confidence: {confidence_zero}")
    assert confidence_zero == Decimal("0.99"), f"Maximum violation should have max confidence 0.99, got {confidence_zero}"
    
    print("✓ Confidence increases with severity")


def test_confidence_orders_without_settlement():
    """Test confidence calculation for orders_without_settlement mode."""
    print("\n=== Test: Confidence for Orders Without Settlement ===")
    
    # Scenario 1: 50% capture rate (bad, 35 points below 85% threshold)
    data_snapshot_severe = {
        "payment_capture_rate": 0.50,
        "captured_payments_inr": 10000,
        "failed_payments_inr": 10000,
    }
    confidence_severe = _calculate_confidence_score("orders_without_settlement", data_snapshot_severe)
    print(f"Capture rate 50% (threshold 85%) → Confidence: {confidence_severe}")
    assert confidence_severe >= Decimal("0.70"), f"Severe failure rate should have high confidence, got {confidence_severe}"
    
    # Scenario 2: 84% capture rate (barely below threshold)
    data_snapshot_mild = {
        "payment_capture_rate": 0.84,
        "captured_payments_inr": 84000,
        "failed_payments_inr": 16000,
    }
    confidence_mild = _calculate_confidence_score("orders_without_settlement", data_snapshot_mild)
    print(f"Capture rate 84% (threshold 85%) → Confidence: {confidence_mild}")
    assert confidence_mild <= Decimal("0.52"), f"Mild violation should have low confidence, got {confidence_mild}"
    
    print("✓ Confidence inversely correlates with capture rate")


def test_confidence_conversion_with_returns():
    """Test confidence calculation for conversion_with_returns mode."""
    print("\n=== Test: Confidence for Conversion With Returns ===")
    
    # Scenario 1: 40% refund rate (severe, 20 points above 20% threshold)
    data_snapshot_severe = {
        "refund_rate": 0.40,
        "refund_amount_inr": 8000,
        "order_revenue_inr": 20000,
    }
    confidence_severe = _calculate_confidence_score("conversion_with_returns", data_snapshot_severe)
    print(f"Refund rate 40% (threshold 20%) → Confidence: {confidence_severe}")
    assert confidence_severe >= Decimal("0.80"), f"High refund rate should have high confidence, got {confidence_severe}"
    
    # Scenario 2: 21% refund rate (barely above threshold)
    data_snapshot_mild = {
        "refund_rate": 0.21,
        "refund_amount_inr": 2100,
        "order_revenue_inr": 10000,
    }
    confidence_mild = _calculate_confidence_score("conversion_with_returns", data_snapshot_mild)
    print(f"Refund rate 21% (threshold 20%) → Confidence: {confidence_mild}")
    assert confidence_mild <= Decimal("0.52"), f"Mild violation should have low confidence, got {confidence_mild}"
    
    print("✓ Confidence correlates with refund rate excess")


def test_confidence_range():
    """Test confidence scores stay in valid range."""
    print("\n=== Test: Confidence Range Boundaries ===")
    
    # Test all three modes with various severities
    test_cases = [
        ("spend_without_conversion", {"roas": 1.49}),  # Just below threshold
        ("spend_without_conversion", {"roas": 0.01}),  # Almost zero
        ("orders_without_settlement", {"payment_capture_rate": 0.84}),  # Just below
        ("orders_without_settlement", {"payment_capture_rate": 0.01}),  # Very low
        ("conversion_with_returns", {"refund_rate": 0.21}),  # Just above
        ("conversion_with_returns", {"refund_rate": 0.49}),  # Very high
    ]
    
    for mode, snapshot in test_cases:
        confidence = _calculate_confidence_score(mode, snapshot)
        assert Decimal("0.50") <= confidence <= Decimal("0.99"), \
            f"Confidence {confidence} for {mode} outside range [0.50, 0.99]"
    
    print(f"✓ All confidence scores in range [0.50, 0.99]")


def main():
    """Run all confidence score tests."""
    print("=" * 60)
    print("TESTING: Confidence Score Calculation")
    print("=" * 60)
    
    test_confidence_spend_without_conversion()
    test_confidence_orders_without_settlement()
    test_confidence_conversion_with_returns()
    test_confidence_range()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
    print("\nConfidence Score Semantics:")
    print("- NOT an LLM probability or Bayesian confidence")
    print("- IS a threshold-distance severity score")
    print("- Range: 0.50 (mild violation) to 0.99 (severe violation)")
    print("- Calculation: severity = how_far_past_threshold / threshold_range")
    print("- Honest, deterministic, explainable to founders")


if __name__ == "__main__":
    main()
