from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from models.enums import MetricType, MONEY_METRICS, Source


class NormalizedMetric(BaseModel):
    """
    The universal normalized row that every connector's normalize() must produce.

    This is the contract between connectors and the rest of the application.
    Pydantic validates every field at construction time — malformed normalization
    raises a ValidationError at the connector boundary, never silently reaching
    the database.

    Field guide:
        merchant_id       Multi-tenancy key. Every query filters on this.
        source            Which connector produced this row (Source enum).
        source_record_id  Original record ID in the source system.
                          Used for provenance and dedup (unique constraint).
        metric_type       What kind of number this is (MetricType enum).
        value             The number. Always Decimal — never float for money.
        currency          ISO 4217 code (e.g. "INR", "USD"). Required for
                          monetary metrics (see MONEY_METRICS). None for counts,
                          ratios, scores.
        date              Business date for time-series analysis. Not a timestamp.
        dimensions        Queryable breakdown axes: campaign_id, SKU, method, etc.
                          Anything product code might GROUP BY or WHERE.
                          Stored as JSONB with a GIN index.
        raw_data          Full API response. Provenance only — product code
                          (chat tools, agent, API routes) must never read this.
        fetched_at        UTC timestamp when the API call was made.
    """

    merchant_id: UUID
    source: Source
    source_record_id: str
    metric_type: MetricType
    value: Decimal
    currency: str | None
    date: date
    dimensions: dict[str, str] | None = None
    raw_data: dict
    fetched_at: datetime

    model_config = {"frozen": True}

    @field_validator("value", mode="before")
    @classmethod
    def coerce_to_decimal(cls, v: object) -> Decimal:
        """
        Accept int, float, str, or Decimal and normalise to Decimal.
        Using str(v) as the intermediate avoids float precision errors.
        e.g. Decimal(str(150.5)) → Decimal("150.5"), not Decimal("150.4999...")
        """
        if isinstance(v, Decimal):
            return v
        try:
            return Decimal(str(v))
        except Exception:
            raise ValueError(f"Cannot convert {v!r} to Decimal")

    @field_validator("currency", mode="before")
    @classmethod
    def normalise_currency(cls, v: object) -> str | None:
        """Upper-case and strip whitespace. None passes through."""
        if v is None:
            return None
        return str(v).strip().upper()

    @field_validator("source_record_id", mode="before")
    @classmethod
    def coerce_record_id_to_str(cls, v: object) -> str:
        """Source APIs often return numeric IDs. Coerce to string."""
        return str(v)

    @model_validator(mode="after")
    def currency_required_for_money(self) -> "NormalizedMetric":
        """
        Monetary metrics must always have a currency.
        Catches connectors that forget to pass currency for revenue/spend rows.
        """
        if self.metric_type in MONEY_METRICS and not self.currency:
            raise ValueError(
                f"metric_type '{self.metric_type.value}' is monetary "
                f"(in MONEY_METRICS) but currency is None or empty. "
                f"source_record_id={self.source_record_id!r}"
            )
        return self
