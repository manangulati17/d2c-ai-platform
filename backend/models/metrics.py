from datetime import datetime, date
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from core.database import Base


class Metric(Base):
    """
    Universal data model — all data from all connectors lands here.
    Every row has full provenance tracking back to the source system.

    Column guide:
        source / source_record_id / raw_data  — provenance
        metric_type / value / currency / date — the measure
        dimensions                            — queryable breakdown axes
                                               (GROUP BY / WHERE in product code)
        raw_data                              — original API response,
                                               NEVER read by product code
    """
    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "source",
            "source_record_id",
            "metric_type",
            name="uq_metric_provenance"
        ),
        Index("ix_metrics_merchant_id", "merchant_id"),
        Index("ix_metrics_date", "date"),
        Index("ix_metrics_merchant_source_date", "merchant_id", "source", "date"),
        # GIN index enables fast JSONB key/value queries on dimensions
        # e.g. WHERE dimensions->>'campaign_id' = 'abc'
        Index("ix_metrics_dimensions", "dimensions", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    merchant_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id"),
        nullable=False,
    )
    # Values come from models.enums.Source — stored as plain string in DB
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String, nullable=False)
    # Values come from models.enums.MetricType — stored as plain string in DB
    metric_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    # ISO 4217 currency code. Required for MONEY_METRICS, None for counts/ratios.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # Queryable breakdown axes: campaign_id, sku, payment_method, courier, etc.
    # Anything product code (chat tools, agent, API) might GROUP BY or WHERE.
    dimensions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Full API response. Provenance only — product code must never read this.
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Metric(id={self.id}, source={self.source}, "
            f"metric_type={self.metric_type}, value={self.value}, date={self.date})>"
        )
