from datetime import datetime, date
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import String, Numeric, Date, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from core.database import Base


class Metric(Base):
    """
    Universal data model - all data from all connectors lands here.
    Every row has full provenance tracking back to the source system.
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
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String, nullable=False)
    metric_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
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
        return f"<Metric(id={self.id}, merchant_id={self.merchant_id}, source={self.source}, metric_type={self.metric_type}, value={self.value})>"
