"""
Chat tool definitions and implementations for querying normalized metrics.

Each tool:
1. Has an OpenAI-compatible JSON schema definition
2. Has an async implementation function that queries the database
3. Returns results with row IDs for citation enforcement

All tools enforce merchant_id filtering (multi-tenancy) on every query.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.metrics import Metric
from models.enums import MetricType, Source


# ============================================================================
# Tool Schema Definitions (OpenAI function calling format)
# ============================================================================

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_metrics_aggregate",
            "description": "Query metrics with aggregation (SUM, AVG, COUNT). Returns aggregated value with list of source row IDs for citation. Use this for questions like 'total revenue', 'average order value', 'ad spend last week'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of metric types to query (e.g., ['order_revenue', 'ad_spend']). Use exact enum values from MetricType."
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["sum", "avg", "count", "min", "max"],
                        "description": "Aggregation function to apply."
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (inclusive)."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (inclusive)."
                    },
                    "source": {
                        "type": "string",
                        "enum": ["shopify", "razorpay", "meta_ads"],
                        "description": "Optional: filter by data source."
                    },
                    "dimension_filters": {
                        "type": "object",
                        "description": "Optional: filter by dimensions (e.g., {'campaign_id': 'xyz', 'financial_status': 'paid'})."
                    }
                },
                "required": ["metric_types", "aggregation", "start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics_timeseries",
            "description": "Query metrics grouped by date (time series). Returns daily values with row IDs for each day. Use for questions like 'revenue by day', 'daily ad spend trend'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of metric types to query."
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["sum", "avg", "count"],
                        "description": "Aggregation function for each day."
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format."
                    },
                    "source": {
                        "type": "string",
                        "enum": ["shopify", "razorpay", "meta_ads"],
                        "description": "Optional: filter by data source."
                    }
                },
                "required": ["metric_types", "aggregation", "start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_metrics_breakdown",
            "description": "Query metrics grouped by a dimension (e.g., by campaign, by product, by payment method). Returns breakdown with row IDs for each group. Use for questions like 'revenue by campaign', 'orders by payment method'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of metric types to query."
                    },
                    "aggregation": {
                        "type": "string",
                        "enum": ["sum", "avg", "count"],
                        "description": "Aggregation function."
                    },
                    "group_by_dimension": {
                        "type": "string",
                        "description": "Dimension key to group by (e.g., 'campaign_id', 'financial_status', 'method')."
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format."
                    },
                    "source": {
                        "type": "string",
                        "enum": ["shopify", "razorpay", "meta_ads"],
                        "description": "Optional: filter by data source."
                    }
                },
                "required": ["metric_types", "aggregation", "group_by_dimension", "start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_roas",
            "description": "Calculate Return on Ad Spend (ROAS) = Revenue / Ad Spend for a date range. Requires both Shopify order revenue and Meta Ads spend data. Returns ROAS with citation to source rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format."
                    }
                },
                "required": ["start_date", "end_date"]
            }
        }
    }
]


# ============================================================================
# Tool Implementation Functions
# ============================================================================

async def query_metrics_aggregate(
    db: AsyncSession,
    merchant_id: UUID,
    metric_types: list[str],
    aggregation: str,
    start_date: str,
    end_date: str,
    source: str | None = None,
    dimension_filters: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Query metrics with aggregation.
    
    Returns:
        {
            "result": <aggregated value>,
            "currency": <currency if applicable>,
            "row_count": <number of rows aggregated>,
            "cited_row_ids": [<list of metric UUIDs>]
        }
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    
    # Build base query
    conditions = [
        Metric.merchant_id == merchant_id,
        Metric.metric_type.in_(metric_types),
        Metric.date >= start,
        Metric.date <= end
    ]
    
    if source:
        conditions.append(Metric.source == source)
    
    if dimension_filters:
        for key, value in dimension_filters.items():
            conditions.append(Metric.dimensions[key].astext == value)
    
    # Get aggregated result
    if aggregation == "sum":
        agg_func = func.sum(Metric.value)
    elif aggregation == "avg":
        agg_func = func.avg(Metric.value)
    elif aggregation == "count":
        agg_func = func.count(Metric.id)
    elif aggregation == "min":
        agg_func = func.min(Metric.value)
    elif aggregation == "max":
        agg_func = func.max(Metric.value)
    else:
        raise ValueError(f"Unknown aggregation: {aggregation}")
    
    agg_query = select(
        agg_func.label("result"),
        func.count(Metric.id).label("row_count")
    ).where(and_(*conditions))
    
    agg_result = await db.execute(agg_query)
    agg_row = agg_result.first()
    
    # Get row IDs for citation
    ids_query = select(Metric.id, Metric.currency).where(and_(*conditions))
    ids_result = await db.execute(ids_query)
    rows = ids_result.all()
    
    cited_row_ids = [str(row.id) for row in rows]
    
    # Determine currency (use first non-null currency found)
    currency = None
    for row in rows:
        if row.currency:
            currency = row.currency
            break
    
    return {
        "result": float(agg_row.result) if agg_row.result is not None else 0.0,
        "currency": currency,
        "row_count": agg_row.row_count,
        "cited_row_ids": cited_row_ids
    }


async def query_metrics_timeseries(
    db: AsyncSession,
    merchant_id: UUID,
    metric_types: list[str],
    aggregation: str,
    start_date: str,
    end_date: str,
    source: str | None = None
) -> dict[str, Any]:
    """
    Query metrics grouped by date.
    
    Returns:
        {
            "timeseries": [
                {
                    "date": "YYYY-MM-DD",
                    "value": <aggregated value>,
                    "cited_row_ids": [<list of metric UUIDs for this date>]
                },
                ...
            ],
            "currency": <currency if applicable>
        }
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    
    conditions = [
        Metric.merchant_id == merchant_id,
        Metric.metric_type.in_(metric_types),
        Metric.date >= start,
        Metric.date <= end
    ]
    
    if source:
        conditions.append(Metric.source == source)
    
    # Get all rows for grouping
    query = select(Metric).where(and_(*conditions)).order_by(Metric.date)
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Group by date in Python (simpler than complex SQLAlchemy grouping)
    from collections import defaultdict
    date_groups = defaultdict(list)
    currency = None
    
    for row in rows:
        date_groups[row.date].append(row)
        if not currency and row.currency:
            currency = row.currency
    
    # Apply aggregation
    timeseries = []
    for date_key in sorted(date_groups.keys()):
        date_rows = date_groups[date_key]
        
        if aggregation == "sum":
            value = sum(float(r.value) for r in date_rows)
        elif aggregation == "avg":
            value = sum(float(r.value) for r in date_rows) / len(date_rows)
        elif aggregation == "count":
            value = len(date_rows)
        else:
            value = 0.0
        
        timeseries.append({
            "date": date_key.isoformat(),
            "value": value,
            "cited_row_ids": [str(r.id) for r in date_rows]
        })
    
    return {
        "timeseries": timeseries,
        "currency": currency
    }


async def query_metrics_breakdown(
    db: AsyncSession,
    merchant_id: UUID,
    metric_types: list[str],
    aggregation: str,
    group_by_dimension: str,
    start_date: str,
    end_date: str,
    source: str | None = None
) -> dict[str, Any]:
    """
    Query metrics grouped by a dimension.
    
    Returns:
        {
            "breakdown": [
                {
                    "dimension_value": <value of the dimension>,
                    "value": <aggregated value>,
                    "cited_row_ids": [<list of metric UUIDs for this group>]
                },
                ...
            ],
            "currency": <currency if applicable>,
            "dimension_key": <the dimension that was grouped by>
        }
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    
    conditions = [
        Metric.merchant_id == merchant_id,
        Metric.metric_type.in_(metric_types),
        Metric.date >= start,
        Metric.date <= end,
        Metric.dimensions.isnot(None),
        Metric.dimensions.has_key(group_by_dimension)
    ]
    
    if source:
        conditions.append(Metric.source == source)
    
    # Get all rows
    query = select(Metric).where(and_(*conditions))
    result = await db.execute(query)
    rows = result.scalars().all()
    
    # Group by dimension value in Python
    from collections import defaultdict
    dimension_groups = defaultdict(list)
    currency = None
    
    for row in rows:
        dim_value = row.dimensions.get(group_by_dimension)
        if dim_value:
            dimension_groups[dim_value].append(row)
            if not currency and row.currency:
                currency = row.currency
    
    # Apply aggregation
    breakdown = []
    for dim_value, dim_rows in dimension_groups.items():
        if aggregation == "sum":
            value = sum(float(r.value) for r in dim_rows)
        elif aggregation == "avg":
            value = sum(float(r.value) for r in dim_rows) / len(dim_rows)
        elif aggregation == "count":
            value = len(dim_rows)
        else:
            value = 0.0
        
        breakdown.append({
            "dimension_value": dim_value,
            "value": value,
            "cited_row_ids": [str(r.id) for r in dim_rows]
        })
    
    # Sort by value descending
    breakdown.sort(key=lambda x: x["value"], reverse=True)
    
    return {
        "breakdown": breakdown,
        "currency": currency,
        "dimension_key": group_by_dimension
    }


async def calculate_roas(
    db: AsyncSession,
    merchant_id: UUID,
    start_date: str,
    end_date: str
) -> dict[str, Any]:
    """
    Calculate Return on Ad Spend (ROAS).
    
    Returns:
        {
            "roas": <revenue / ad_spend>,
            "revenue": <total revenue>,
            "ad_spend": <total ad spend>,
            "revenue_currency": <currency>,
            "ad_spend_currency": <currency>,
            "revenue_cited_row_ids": [<list of revenue metric UUIDs>],
            "ad_spend_cited_row_ids": [<list of ad spend metric UUIDs>]
        }
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    
    # Get revenue (Shopify ORDER_REVENUE)
    revenue_query = select(Metric).where(
        and_(
            Metric.merchant_id == merchant_id,
            Metric.metric_type == MetricType.ORDER_REVENUE.value,
            Metric.date >= start,
            Metric.date <= end
        )
    )
    revenue_result = await db.execute(revenue_query)
    revenue_rows = revenue_result.scalars().all()
    
    total_revenue = sum(float(r.value) for r in revenue_rows)
    revenue_currency = revenue_rows[0].currency if revenue_rows else None
    revenue_row_ids = [str(r.id) for r in revenue_rows]
    
    # Get ad spend (Meta Ads AD_SPEND)
    ad_spend_query = select(Metric).where(
        and_(
            Metric.merchant_id == merchant_id,
            Metric.metric_type == MetricType.AD_SPEND.value,
            Metric.date >= start,
            Metric.date <= end
        )
    )
    ad_spend_result = await db.execute(ad_spend_query)
    ad_spend_rows = ad_spend_result.scalars().all()
    
    total_ad_spend = sum(float(r.value) for r in ad_spend_rows)
    ad_spend_currency = ad_spend_rows[0].currency if ad_spend_rows else None
    ad_spend_row_ids = [str(r.id) for r in ad_spend_rows]
    
    # Calculate ROAS
    roas = total_revenue / total_ad_spend if total_ad_spend > 0 else 0.0
    
    return {
        "roas": roas,
        "revenue": total_revenue,
        "ad_spend": total_ad_spend,
        "revenue_currency": revenue_currency,
        "ad_spend_currency": ad_spend_currency,
        "revenue_cited_row_ids": revenue_row_ids,
        "ad_spend_cited_row_ids": ad_spend_row_ids
    }


# ============================================================================
# Tool Dispatcher
# ============================================================================

TOOL_IMPLEMENTATIONS = {
    "query_metrics_aggregate": query_metrics_aggregate,
    "query_metrics_timeseries": query_metrics_timeseries,
    "query_metrics_breakdown": query_metrics_breakdown,
    "calculate_roas": calculate_roas,
}


async def execute_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    db: AsyncSession,
    merchant_id: UUID
) -> dict[str, Any]:
    """
    Execute a tool by name with the given arguments.
    
    Args:
        tool_name: Name of the tool function
        tool_args: Arguments to pass to the tool
        db: Database session
        merchant_id: Merchant ID for multi-tenancy filtering
    
    Returns:
        Tool execution result
    
    Raises:
        ValueError: If tool_name is not recognized
    """
    if tool_name not in TOOL_IMPLEMENTATIONS:
        raise ValueError(f"Unknown tool: {tool_name}")
    
    tool_func = TOOL_IMPLEMENTATIONS[tool_name]
    
    # Inject db and merchant_id
    return await tool_func(db=db, merchant_id=merchant_id, **tool_args)
