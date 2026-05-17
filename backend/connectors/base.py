from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from connectors.schema import NormalizedMetric
from models.enums import MetricType, Source


class BaseConnector(ABC):
    """
    Abstract base class for all SaaS connector implementations.

    All connectors (Shopify, Razorpay, Meta Ads) must inherit from this class
    and implement fetch() and normalize(). This ensures a consistent interface
    and makes connectors swappable — WooCommerce can replace Shopify without
    touching the chat layer, the agent, or any other code.

    Lifecycle:
        1. Instantiate with merchant_id + config (from merchant_connectors.config)
        2. Call sync(start_date, end_date)
        3. sync() calls fetch() → normalize() and returns validated NormalizedMetric rows
        4. Caller inserts rows into the metrics table

    Normalization contract:
        - normalize() MUST return list[NormalizedMetric], not list[dict]
        - Use _make_metric() to construct rows — never build NormalizedMetric by hand
        - One source record fans out to many rows (one per MetricType)
        - All fan-out rows share the same source_record_id
        - raw_data stores the full API response; product code NEVER reads it
        - dimensions stores queryable breakdown axes (campaign, SKU, method, etc.)

    Class variables:
        source (Source): Must be set by each subclass to the matching Source enum value.
    """

    source: Source = None

    def __init__(self, merchant_id: UUID, config: dict[str, Any]) -> None:
        """
        Args:
            merchant_id: UUID of the merchant this connector fetches data for.
                        Stamped on every NormalizedMetric row for multi-tenancy.
            config: Connector credentials and settings loaded from
                   merchant_connectors.config JSONB field. Structure varies by
                   connector (API keys, store URLs, account IDs, etc.)

        Raises:
            ValueError: If the subclass has not set the source class variable.
        """
        if self.source is None:
            raise ValueError(
                f"{self.__class__.__name__} must set 'source' class variable "
                f"to a models.enums.Source value"
            )
        self.merchant_id = merchant_id
        self.config = config

    @abstractmethod
    async def fetch(self, start_date: date, end_date: date) -> list[dict]:
        """
        Fetch raw data from the external SaaS API for the given date range.

        Responsibilities:
        - Authenticate using credentials from self.config
        - Request data covering [start_date, end_date] inclusive
        - Handle pagination (accumulate all pages before returning)
        - Return raw API responses with minimal processing

        Args:
            start_date: Start of date range (inclusive).
            end_date:   End of date range (inclusive).

        Returns:
            List of raw API response dicts. One dict = one source record
            (one order, one payment, one ad insight row, etc.).

        Raises:
            Exception: Auth failures, network errors, API errors. The caller
                      (sync job / agent) is responsible for logging these.
        """

    @abstractmethod
    async def normalize(self, raw_data: list[dict]) -> list[NormalizedMetric]:
        """
        Transform raw API data into validated NormalizedMetric rows.

        Responsibilities:
        - Call self._make_metric() for each metric extracted from a record
        - Fan out: one record → many NormalizedMetric rows (one per MetricType)
        - Put queryable breakdown axes in dimensions (campaign, SKU, method…)
        - Never embed logic that reads raw_data elsewhere in the codebase

        Args:
            raw_data: List of raw dicts from fetch().

        Returns:
            List of validated NormalizedMetric instances, ready for DB insertion.
            Empty list is valid (e.g. all records outside date range).
        """

    async def sync(self, start_date: date, end_date: date) -> list[NormalizedMetric]:
        """
        Fetch and normalize data in one call. The only public method callers use.

        Orchestrates fetch() → normalize() and returns validated rows ready
        for insertion into the metrics table.

        Args:
            start_date: Start of date range (inclusive).
            end_date:   End of date range (inclusive).

        Returns:
            List of validated NormalizedMetric rows.

        Raises:
            Exception: Propagates from fetch() or normalize(). Caller should
                      handle and log to agent_logs when appropriate.
        """
        raw_data = await self.fetch(start_date, end_date)
        return await self.normalize(raw_data)

    def _make_metric(
        self,
        *,
        source_record_id: str | int,
        metric_type: MetricType,
        value: Decimal | int | float | str,
        date: date,
        currency: str | None = None,
        dimensions: dict[str, str] | None = None,
        raw_data: dict,
        fetched_at: datetime | None = None,
    ) -> NormalizedMetric:
        """
        Construct a validated NormalizedMetric for this connector.

        Auto-fills merchant_id and source from the connector instance.
        Coerces value to Decimal and source_record_id to str.
        Defaults fetched_at to UTC now if not supplied.

        Use this instead of constructing NormalizedMetric directly —
        it ensures every row has the correct merchant_id and source.

        Args:
            source_record_id: Original record ID from the source system.
                             Numbers are coerced to str automatically.
            metric_type:      MetricType enum value for this row.
            value:            The numeric measurement. Accepts Decimal, int,
                             float, or str — all coerced to Decimal safely.
            date:             Business date for time-series analysis.
            currency:         ISO 4217 code (e.g. "INR"). Required for
                             MONEY_METRICS; pass None for counts and ratios.
            dimensions:       Queryable breakdown axes. Use string keys and
                             string values. Example:
                             {"campaign_id": "abc", "platform": "instagram"}
            raw_data:         Full API response dict for provenance. Product
                             code must never read this field.
            fetched_at:       UTC timestamp of the API call. Defaults to now.

        Returns:
            A validated NormalizedMetric instance.

        Raises:
            pydantic.ValidationError: If required fields are missing or the
                                     currency contract is violated.
        """
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc)

        return NormalizedMetric(
            merchant_id=self.merchant_id,
            source=self.source,
            source_record_id=str(source_record_id),
            metric_type=metric_type,
            value=value,
            currency=currency,
            date=date,
            dimensions=dimensions,
            raw_data=raw_data,
            fetched_at=fetched_at,
        )
