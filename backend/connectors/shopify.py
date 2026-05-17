from datetime import date, datetime
from typing import Any
from uuid import UUID

import httpx

from connectors.base import BaseConnector
from connectors.registry import register
from connectors.schema import NormalizedMetric
from models.enums import MetricType, Source


@register
class ShopifyConnector(BaseConnector):
    """
    Shopify connector — fetches order data from Shopify Admin API.

    Config requirements:
        store_url:     Shopify store domain (e.g. "mystore.myshopify.com")
        access_token:  Shopify Admin API access token

    Normalization:
        One Shopify order fans out to multiple metric rows:
        - ORDER_REVENUE (always)
        - ORDER_COUNT (always)
        - ORDER_TAX (if tax > 0)
        - ORDER_SHIPPING (if shipping fee collected)
        - ORDER_DISCOUNT (if discount applied)
        - ORDER_REFUND (if refund issued)

    All rows share the same source_record_id (order ID).
    """

    source = Source.SHOPIFY

    def __init__(self, merchant_id: UUID, config: dict[str, Any]) -> None:
        """
        Validate config and initialize connector.

        Raises:
            ValueError: If store_url or access_token missing from config.
        """
        super().__init__(merchant_id, config)

        # Fail fast if config is incomplete
        if "store_url" not in config:
            raise ValueError("Shopify config missing 'store_url'")
        if "access_token" not in config:
            raise ValueError("Shopify config missing 'access_token'")

        self.store_url = config["store_url"]
        self.access_token = config["access_token"]

    async def fetch(self, start_date: date, end_date: date) -> list[dict]:
        """
        Fetch all orders from Shopify within the date range.

        Handles pagination automatically by following Link headers.

        Args:
            start_date: Inclusive start date.
            end_date:   Inclusive end date.

        Returns:
            List of order dicts from Shopify API.

        Raises:
            httpx.HTTPStatusError: On API errors (auth, rate limit, etc.).
        """
        orders = []

        # Initial request
        url = f"https://{self.store_url}/admin/api/2024-01/orders.json"
        params = {
            "created_at_min": f"{start_date}T00:00:00Z",
            "created_at_max": f"{end_date}T23:59:59Z",
            "status": "any",
            "limit": 250,
        }
        headers = {
            "X-Shopify-Access-Token": self.access_token,
        }

        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()

                data = response.json()
                orders.extend(data.get("orders", []))

                # Check for pagination
                link_header = response.headers.get("Link")
                url = self._parse_next_link(link_header)
                params = None  # Next URL is complete, no params needed

        return orders

    def _parse_next_link(self, link_header: str | None) -> str | None:
        """
        Extract the next page URL from Shopify's Link header.

        Shopify returns: Link: <https://...>; rel="next", <https://...>; rel="previous"

        Args:
            link_header: Raw Link header value.

        Returns:
            Next page URL if present, None otherwise.
        """
        if not link_header:
            return None

        links = link_header.split(",")
        for link in links:
            parts = link.split(";")
            if len(parts) == 2:
                url = parts[0].strip().strip("<>")
                rel = parts[1].strip()
                if 'rel="next"' in rel:
                    return url

        return None

    async def normalize(self, raw_data: list[dict]) -> list[NormalizedMetric]:
        """
        Transform Shopify orders into NormalizedMetric rows.

        Each order produces multiple rows (fan-out pattern).

        Args:
            raw_data: List of order dicts from fetch().

        Returns:
            List of validated NormalizedMetric instances.
        """
        metrics = []

        for order in raw_data:
            order_id = str(order["id"])
            currency = order["currency"]

            # Parse order date
            created_at_str = order["created_at"]
            order_date = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).date()

            # ORDER_REVENUE — always present
            metrics.append(
                self._make_metric(
                    source_record_id=order_id,
                    metric_type=MetricType.ORDER_REVENUE,
                    value=float(order["total_price"]),
                    date=order_date,
                    currency=currency,
                    dimensions={"financial_status": order.get("financial_status")},
                    raw_data=order,
                )
            )

            # ORDER_COUNT — always 1 per order
            metrics.append(
                self._make_metric(
                    source_record_id=order_id,
                    metric_type=MetricType.ORDER_COUNT,
                    value=1,
                    date=order_date,
                    currency=None,
                    raw_data=order,
                )
            )

            # ORDER_TAX — if tax charged
            total_tax = float(order.get("total_tax", 0))
            if total_tax > 0:
                metrics.append(
                    self._make_metric(
                        source_record_id=order_id,
                        metric_type=MetricType.ORDER_TAX,
                        value=total_tax,
                        date=order_date,
                        currency=currency,
                        raw_data=order,
                    )
                )

            # ORDER_SHIPPING — if shipping fee collected
            shipping_price_set = order.get("total_shipping_price_set", {})
            shop_money = shipping_price_set.get("shop_money", {})
            shipping_amount = shop_money.get("amount")
            if shipping_amount is not None:
                shipping_value = float(shipping_amount)
                if shipping_value > 0:
                    metrics.append(
                        self._make_metric(
                            source_record_id=order_id,
                            metric_type=MetricType.ORDER_SHIPPING,
                            value=shipping_value,
                            date=order_date,
                            currency=currency,
                            raw_data=order,
                        )
                    )

            # ORDER_DISCOUNT — if discount applied
            total_discounts = float(order.get("total_discounts", 0))
            if total_discounts > 0:
                metrics.append(
                    self._make_metric(
                        source_record_id=order_id,
                        metric_type=MetricType.ORDER_DISCOUNT,
                        value=total_discounts,
                        date=order_date,
                        currency=currency,
                        raw_data=order,
                    )
                )

            # ORDER_REFUND — if refund issued
            total_refunded = float(order.get("total_refunded", 0))
            if total_refunded > 0:
                metrics.append(
                    self._make_metric(
                        source_record_id=order_id,
                        metric_type=MetricType.ORDER_REFUND,
                        value=total_refunded,
                        date=order_date,
                        currency=currency,
                        raw_data=order,
                    )
                )

        return metrics
