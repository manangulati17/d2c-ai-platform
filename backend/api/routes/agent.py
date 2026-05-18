"""
Agent API routes.

Endpoints:
- GET /merchants/{merchant_id}/agent/logs — list agent run logs
- GET /merchants/{merchant_id}/agent/logs/{log_id} — get single log
- POST /merchants/{merchant_id}/agent/run — manually trigger agent run
"""

from uuid import UUID
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from models.merchant import Merchant
from models.agent_log import AgentLog
from agent.tasks import run_attribution_agent


router = APIRouter(prefix="/merchants", tags=["agent"])


# ── Pydantic schemas ───────────────────────────────────────────────────────


class AgentLogListResponse(BaseModel):
    """Response schema for agent log list (summary only)."""
    id: UUID
    run_at: datetime
    trigger: str
    detection_mode: str | None
    status: str
    confidence_score: Decimal | None

    class Config:
        from_attributes = True


class AgentLogDetailResponse(BaseModel):
    """Response schema for single agent log (full details)."""
    id: UUID
    merchant_id: UUID
    run_at: datetime
    trigger: str
    detection_mode: str | None
    data_snapshot: dict
    reasoning: str | None
    recommendation: str | None
    confidence_score: Decimal | None
    cited_metric_ids: list | None
    status: str
    error: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentRunResponse(BaseModel):
    """Response schema for manual agent run trigger."""
    merchant_id: UUID
    task_id: str
    status: str
    message: str


# ── Route handlers ─────────────────────────────────────────────────────────


@router.get("/{merchant_id}/agent/logs", response_model=list[AgentLogListResponse])
async def list_agent_logs(
    merchant_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
) -> list[AgentLogListResponse]:
    """
    List agent run logs for a merchant.
    
    Returns logs in reverse chronological order (newest first).
    
    Query params:
        - limit: Number of logs to return (default 20, max 100)
        - offset: Number of logs to skip (default 0)
    
    Returns:
        - 200: List of agent logs
        - 404: Merchant not found
    """
    # Check merchant exists
    result = await db.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()
    
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant {merchant_id} not found"
        )
    
    # Get logs
    result = await db.execute(
        select(AgentLog)
        .where(AgentLog.merchant_id == merchant_id)
        .order_by(AgentLog.run_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    
    return [AgentLogListResponse.model_validate(log) for log in logs]


@router.get("/{merchant_id}/agent/logs/{log_id}", response_model=AgentLogDetailResponse)
async def get_agent_log(
    merchant_id: UUID,
    log_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> AgentLogDetailResponse:
    """
    Get a single agent log with full details.
    
    Returns:
        - 200: Agent log found
        - 404: Merchant or log not found
    """
    # Check merchant exists
    result = await db.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()
    
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant {merchant_id} not found"
        )
    
    # Get log
    result = await db.execute(
        select(AgentLog).where(
            AgentLog.id == log_id,
            AgentLog.merchant_id == merchant_id
        )
    )
    log = result.scalar_one_or_none()
    
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent log {log_id} not found for merchant {merchant_id}"
        )
    
    return AgentLogDetailResponse.model_validate(log)


@router.post("/{merchant_id}/agent/run", response_model=AgentRunResponse)
async def trigger_agent_run(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> AgentRunResponse:
    """
    Manually trigger an agent run for this merchant.

    The agent will analyze the last 7 days of data and log its findings.
    Runs asynchronously via Celery worker.
    Note: The agent observes only and takes no live actions.

    Returns:
        - 200: Agent run queued successfully
        - 404: Merchant not found
    """
    # Check merchant exists and is active
    result = await db.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()

    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant {merchant_id} not found"
        )

    if not merchant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Merchant {merchant_id} is inactive"
        )

    task = run_attribution_agent.delay(str(merchant_id))

    return AgentRunResponse(
        merchant_id=merchant_id,
        task_id=task.id,
        status="queued",
        message="Agent run queued successfully. The agent will analyze the last 7 days of data and log its findings. Note: The agent observes only and takes no live actions. (Requires Celery worker running)"
    )
