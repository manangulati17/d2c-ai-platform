from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from connectors.base import BaseConnector
from connectors.registry import register
from connectors.schema import NormalizedMetric
from models.enums import MetricType, Source


@register
class RazorpayConnector(BaseConnector):
    """
    Razorpay connector — fetches payment, settlement, and refund data from Razorpay API.

    Config requirements:
        key_id:     Razorpay API Key ID
        key_secret: Razorpay API Key Secret

    Normalization:
        Fetches from three endpoints and produces metric rows:
        - Payments → PAYMENT_CAPTURED (captured) or PAYMENT_FAILED (failed)
        - Settlements → SETTLEMENT_AMOUNT
        - Refunds → REFUND_AMOUNT

    Each payment/settlement/refund produces one metric row.
    """

    source = Source.RAZORPAY

    def __init__(self, merchant_id: UUID, config: dict[str, Any]) -> None:
        """
        Validate config and initialize connector.

        Raises:
            ValueError: If key_id or key_secret missing from config.
        """
        super().__init__(merchant_id, config)

        # Fail fast if config is incomplete
        if "key_id" not in config:
            raise ValueError("Razorpay config missing 'key_id'")
        if "key_secret" not in config:
            raise ValueError("Razorpay config missing 'key_secret'")

        self.key_id = config["key_id"]
        self.key_secret = config["key_secret"]

    async def fetch(self, start_date: date, end_date: date) -> list[dict]:
        """
        Fetch payments, settlements, and refunds from Razorpay within the date range.

        Razorpay uses Unix timestamps and skip/count pagination.

        Args:
            start_date: Inclusive start date.
            end_date:   Inclusive end date.

        Returns:
            List of raw API response dicts with "_razorpay_type" discriminator field.
            Each dict represents one payment, settlement, or refund record.

        Raises:
            httpx.HTTPStatusError: On API errors (auth, rate limit, etc.).
        """
        # Convert dates to Unix timestamps (Razorpay expects seconds since epoch)
        from_ts = int(datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
        to_ts = int(datetime.combine(end_date, datetime.max.time()).replace(tzinfo=timezone.utc).timestamp())

        # Fetch from all three endpoints
        payments = await self._fetch_paginated("payments", from_ts, to_ts)
        settlements = await self._fetch_paginated("settlements", from_ts, to_ts)
        refunds = await self._fetch_paginated("refunds", from_ts, to_ts)

        # Flatten into single list with type discriminator
        # This maintains the base class contract of list[dict]
        return (
            [{**p, "_razorpay_type": "payment"} for p in payments]
            + [{**s, "_razorpay_type": "settlement"} for s in settlements]
            + [{**r, "_razorpay_type": "refund"} for r in refunds]
        )

    async def _fetch_paginated(
        self, endpoint: str, from_ts: int, to_ts: int
    ) -> list[dict]:
        """
        Fetch all pages from a Razorpay endpoint using skip/count pagination.

        Args:
            endpoint: API endpoint name (payments, settlements, refunds).
            from_ts:  Start timestamp (Unix seconds).
            to_ts:    End timestamp (Unix seconds).

        Returns:
            List of all items from all pages.
        """
        items = []
        skip = 0
        count = 100  # Razorpay max per page

        async with httpx.AsyncClient() as client:
            while True:
                url = f"https://api.razorpay.com/v1/{endpoint}"
                params = {
                    "from": from_ts,
                    "to": to_ts,
                    "count": count,
                    "skip": skip,
                }

                response = await client.get(
                    url,
                    params=params,
                    auth=(self.key_id, self.key_secret),  # Basic Auth
                )
                response.raise_for_status()

                data = response.json()
                page_items = data.get("items", [])
                items.extend(page_items)

                # Stop if we got fewer items than requested (last page)
                if len(page_items) < count:
                    break

                skip += count

        return items

    async def normalize(self, raw_data: list[dict]) -> list[NormalizedMetric]:
        """
        Transform Razorpay data into NormalizedMetric rows.

        Args:
            raw_data: List of dicts from fetch(), each with "_razorpay_type" discriminator.

        Returns:
            List of validated NormalizedMetric instances.
        """
        metrics = []

        for record in raw_data:
            record_type = record.get("_razorpay_type")
            
            if record_type == "payment":
                # Process payment
                payment_id = str(record["id"])
                
                # Razorpay stores amounts in smallest currency unit (paisa for INR)
                # Convert to major unit (rupees)
                amount = int(record["amount"]) / 100
                currency = record["currency"]
                
                # Parse payment date from Unix timestamp
                created_at = record["created_at"]
                payment_date = datetime.fromtimestamp(created_at, tz=timezone.utc).date()

                # Check payment status
                status = record.get("status", "")
                
                if status == "captured":
                    metrics.append(
                        self._make_metric(
                            source_record_id=payment_id,
                            metric_type=MetricType.PAYMENT_CAPTURED,
                            value=amount,
                            date=payment_date,
                            currency=currency,
                            dimensions={
                                "method": record.get("method", ""),
                                "status": status,
                            },
                            raw_data=record,
                        )
                    )
                elif status == "failed":
                    metrics.append(
                        self._make_metric(
                            source_record_id=payment_id,
                            metric_type=MetricType.PAYMENT_FAILED,
                            value=amount,
                            date=payment_date,
                            currency=currency,
                            dimensions={
                                "method": record.get("method", ""),
                                "error_code": record.get("error_code", ""),
                                "error_description": record.get("error_description", ""),
                            },
                            raw_data=record,
                        )
                    )

            elif record_type == "settlement":
                # Process settlement
                settlement_id = str(record["id"])
                
                # Convert paisa to rupees
                amount = int(record["amount"]) / 100
                currency = record.get("currency", "INR")
                
                # Parse settlement date
                created_at = record["created_at"]
                settlement_date = datetime.fromtimestamp(created_at, tz=timezone.utc).date()

                metrics.append(
                    self._make_metric(
                        source_record_id=settlement_id,
                        metric_type=MetricType.SETTLEMENT_AMOUNT,
                        value=amount,
                        date=settlement_date,
                        currency=currency,
                        dimensions={
                            "utr": record.get("utr", ""),
                            "status": record.get("status", ""),
                        },
                        raw_data=record,
                    )
                )

            elif record_type == "refund":
                # Process refund
                refund_id = str(record["id"])
                
                # Convert paisa to rupees
                amount = int(record["amount"]) / 100
                currency = record.get("currency", "INR")
                
                # Parse refund date
                created_at = record["created_at"]
                refund_date = datetime.fromtimestamp(created_at, tz=timezone.utc).date()

                metrics.append(
                    self._make_metric(
                        source_record_id=refund_id,
                        metric_type=MetricType.REFUND_AMOUNT,
                        value=amount,
                        date=refund_date,
                        currency=currency,
                        dimensions={
                            "payment_id": record.get("payment_id", ""),
                            "speed": record.get("speed", ""),
                            "status": record.get("status", ""),
                        },
                        raw_data=record,
                    )
                )

        return metrics
