from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID
import json

import httpx

from connectors.base import BaseConnector
from connectors.registry import register
from connectors.schema import NormalizedMetric
from models.enums import MetricType, Source


@register
class MetaAdsConnector(BaseConnector):
    """
    Meta Ads connector — fetches ad performance data from Meta Marketing API.

    Config requirements:
        access_token:  Meta Marketing API access token
        ad_account_id: Meta Ad Account ID (format: act_123456789)

    Normalization:
        Each daily insight record fans out to multiple metric rows:
        - AD_SPEND (always)
        - AD_IMPRESSIONS (always)
        - AD_CLICKS (always)
        - AD_CONVERSIONS (if actions contain purchase/lead/conversion events)

    All rows from one insight share the same source_record_id.
    """

    source = Source.META_ADS

    def __init__(self, merchant_id: UUID, config: dict[str, Any]) -> None:
        """
        Validate config and initialize connector.

        Raises:
            ValueError: If access_token or ad_account_id missing from config.
        """
        super().__init__(merchant_id, config)

        # Fail fast if config is incomplete
        if "access_token" not in config:
            raise ValueError("Meta Ads config missing 'access_token'")
        if "ad_account_id" not in config:
            raise ValueError("Meta Ads config missing 'ad_account_id'")

        self.access_token = config["access_token"]
        self.ad_account_id = config["ad_account_id"]

    async def fetch(self, start_date: date, end_date: date) -> list[dict]:
        """
        Fetch ad insights from Meta Marketing API within the date range.

        Uses cursor-based pagination to retrieve all insights.

        Args:
            start_date: Inclusive start date.
            end_date:   Inclusive end date.

        Returns:
            List of insight dicts from Meta API.

        Raises:
            httpx.HTTPStatusError: On API errors (auth, rate limit, etc.).
        """
        insights = []

        # Meta API endpoint
        base_url = f"https://graph.facebook.com/v18.0/{self.ad_account_id}/insights"

        # Query parameters
        params = {
            "access_token": self.access_token,
            "time_range": json.dumps({"since": str(start_date), "until": str(end_date)}),
            "time_increment": "1",  # Daily breakdown
            "level": "ad",  # Get data at ad level
            "fields": ",".join([
                "campaign_id",
                "campaign_name",
                "adset_id",
                "adset_name",
                "ad_id",
                "ad_name",
                "date_start",
                "date_stop",
                "spend",
                "impressions",
                "clicks",
                "actions",  # Contains conversions
                "action_values",
                "account_currency",
            ]),
            "limit": 100,  # Max per page
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            url = base_url
            
            while url:
                response = await client.get(url, params=params if url == base_url else None)
                response.raise_for_status()

                data = response.json()
                insights.extend(data.get("data", []))

                # Check for next page (cursor-based pagination)
                paging = data.get("paging", {})
                next_url = paging.get("next")
                
                if next_url:
                    url = next_url
                    params = None  # Next URL is complete with all params
                else:
                    url = None

        return insights

    async def normalize(self, raw_data: list[dict]) -> list[NormalizedMetric]:
        """
        Transform Meta Ads insights into NormalizedMetric rows.

        Each insight record produces multiple rows (fan-out pattern).

        Args:
            raw_data: List of insight dicts from fetch().

        Returns:
            List of validated NormalizedMetric instances.
        """
        metrics = []

        for insight in raw_data:
            # Generate unique source_record_id from ad_id and date
            ad_id = insight.get("ad_id", "unknown")
            date_start = insight.get("date_start", "")
            source_record_id = f"{ad_id}_{date_start}"

            # Parse date
            insight_date = datetime.strptime(date_start, "%Y-%m-%d").date()

            # Get currency
            currency = insight.get("account_currency", "USD")

            # Build dimensions with campaign/adset/ad hierarchy
            dimensions = {
                "campaign_id": insight.get("campaign_id", ""),
                "campaign_name": insight.get("campaign_name", ""),
                "adset_id": insight.get("adset_id", ""),
                "adset_name": insight.get("adset_name", ""),
                "ad_id": insight.get("ad_id", ""),
                "ad_name": insight.get("ad_name", ""),
            }

            # AD_SPEND — always present
            spend = float(insight.get("spend", 0))
            metrics.append(
                self._make_metric(
                    source_record_id=source_record_id,
                    metric_type=MetricType.AD_SPEND,
                    value=spend,
                    date=insight_date,
                    currency=currency,
                    dimensions=dimensions,
                    raw_data=insight,
                )
            )

            # AD_IMPRESSIONS — always present (count metric, no currency)
            impressions = int(insight.get("impressions", 0))
            metrics.append(
                self._make_metric(
                    source_record_id=source_record_id,
                    metric_type=MetricType.AD_IMPRESSIONS,
                    value=impressions,
                    date=insight_date,
                    currency=None,
                    dimensions=dimensions,
                    raw_data=insight,
                )
            )

            # AD_CLICKS — always present (count metric, no currency)
            clicks = int(insight.get("clicks", 0))
            metrics.append(
                self._make_metric(
                    source_record_id=source_record_id,
                    metric_type=MetricType.AD_CLICKS,
                    value=clicks,
                    date=insight_date,
                    currency=None,
                    dimensions=dimensions,
                    raw_data=insight,
                )
            )

            # AD_CONVERSIONS — extract from actions array
            # Meta returns actions as: [{"action_type": "purchase", "value": "12"}, ...]
            actions = insight.get("actions", [])
            total_conversions = 0

            if actions:
                # Sum conversions from relevant action types
                conversion_types = {
                    "purchase",
                    "lead",
                    "complete_registration",
                    "add_to_cart",
                    "initiate_checkout",
                    "offsite_conversion.fb_pixel_purchase",
                }

                for action in actions:
                    action_type = action.get("action_type", "")
                    if action_type in conversion_types:
                        total_conversions += int(float(action.get("value", 0)))

            if total_conversions > 0:
                # Include conversion breakdown in dimensions
                conversion_dims = dimensions.copy()
                conversion_dims["conversion_types"] = ",".join(
                    action.get("action_type", "")
                    for action in actions
                    if action.get("action_type", "") in conversion_types
                )

                metrics.append(
                    self._make_metric(
                        source_record_id=source_record_id,
                        metric_type=MetricType.AD_CONVERSIONS,
                        value=total_conversions,
                        date=insight_date,
                        currency=None,
                        dimensions=conversion_dims,
                        raw_data=insight,
                    )
                )

        return metrics
