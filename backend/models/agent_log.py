from datetime import datetime
from uuid import uuid4
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from core.database import Base


class AgentLog(Base):
    """
    Audit trail for Full-Funnel Attribution Agent runs.
    Stores reasoning, recommendations, and data snapshot for every execution.
    Proves the agent's decision-making is transparent and traceable.
    Maintains citation contract: cited_metric_ids references source metrics.
    """
    __tablename__ = "agent_logs"
    __table_args__ = (
        Index("ix_agent_logs_merchant_id", "merchant_id"),
        Index("ix_agent_logs_merchant_run_at", "merchant_id", "run_at"),
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
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    detection_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    data_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    cited_metric_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, default="completed", server_default="completed", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<AgentLog(id={self.id}, merchant_id={self.merchant_id}, detection_mode={self.detection_mode}, status={self.status})>"
