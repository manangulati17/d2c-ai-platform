from enum import Enum


class Source(str, Enum):
    """
    Identifies which SaaS connector produced a metric row.
    Adding a new connector requires adding a value here first,
    then writing the connector file.
    """
    SHOPIFY    = "shopify"
    RAZORPAY   = "razorpay"
    META_ADS   = "meta_ads"


class MetricType(str, Enum):
    """
    The closed vocabulary of every metric the platform understands.
    Grouped by source for readability; the DB stores the string value.

    Adding a new connector: extend this enum with the connector's metrics,
    then implement its normalize() using these values.

    Fan-out: one source record produces one row per applicable MetricType.
    All rows share the same source_record_id — the unique constraint
    (merchant_id, source, source_record_id, metric_type) handles dedup.
    """

    # ── Shopify ────────────────────────────────────────────────────────────
    ORDER_REVENUE   = "order_revenue"   # gross order amount (before deductions)
    ORDER_COUNT     = "order_count"     # always 1.0 — used for counting orders
    ORDER_DISCOUNT  = "order_discount"  # total discount applied to the order
    ORDER_TAX       = "order_tax"       # tax charged on the order
    ORDER_SHIPPING  = "order_shipping"  # shipping fee collected
    ORDER_REFUND    = "order_refund"    # refunded amount (positive number)

    # ── Razorpay ───────────────────────────────────────────────────────────
    PAYMENT_CAPTURED   = "payment_captured"   # successfully captured payment
    PAYMENT_FAILED     = "payment_failed"     # failed payment attempt (value = attempted amount)
    SETTLEMENT_AMOUNT  = "settlement_amount"  # amount settled to merchant's bank
    REFUND_AMOUNT      = "refund_amount"      # refund issued via Razorpay

    # ── Meta Ads ───────────────────────────────────────────────────────────
    AD_SPEND       = "ad_spend"        # money spent on ads
    AD_IMPRESSIONS = "ad_impressions"  # number of impressions (no currency)
    AD_CLICKS      = "ad_clicks"       # number of clicks (no currency)
    AD_CONVERSIONS = "ad_conversions"  # number of conversions (no currency)

    # ── Custom / free-form (Google Sheets, CSV, future connectors) ─────────
    # The actual metric name lives in dimensions->>'metric_name'.
    # Product code queries: WHERE metric_type = 'custom_amount'
    #                       AND dimensions->>'metric_name' = 'influencer_revenue'
    CUSTOM_AMOUNT  = "custom_amount"   # monetary custom metric, currency required
    CUSTOM_COUNT   = "custom_count"    # integer-style custom metric, no currency
    CUSTOM_NUMERIC = "custom_numeric"  # any decimal (rate, score, ratio), no currency


# Metric types that represent money — currency must be non-null for these.
# Used by NormalizedMetric's currency validator.
MONEY_METRICS: frozenset[MetricType] = frozenset({
    MetricType.ORDER_REVENUE,
    MetricType.ORDER_DISCOUNT,
    MetricType.ORDER_TAX,
    MetricType.ORDER_SHIPPING,
    MetricType.ORDER_REFUND,
    MetricType.PAYMENT_CAPTURED,
    MetricType.PAYMENT_FAILED,
    MetricType.SETTLEMENT_AMOUNT,
    MetricType.REFUND_AMOUNT,
    MetricType.AD_SPEND,
    MetricType.CUSTOM_AMOUNT,
})
