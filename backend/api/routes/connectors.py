"""
Connector management and sync API routes.

Endpoints:
- POST /merchants/{merchant_id}/connectors — register a connector
- GET /merchants/{merchant_id}/connectors — list connectors
- POST /merchants/{merchant_id}/connectors/{source}/sync — trigger sync
- GET /merchants/{merchant_id}/connectors/{source}/status — last sync info
"""

from uuid import UUID
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel

from core.database import get_db
from models.merchant import Merchant, MerchantConnector
from models.metrics import Metric
from models.enums import Source
from connectors import get_connector


router = APIRouter(prefix="/merchants", tags=["connectors"])


# ── Pydantic schemas ───────────────────────────────────────────────────────


class ConnectorCreate(BaseModel):
    """Request schema for registering a connector."""
    connector_type: Source
    config: dict


class ConnectorResponse(BaseModel):
    """Response schema for connector data."""
    id: UUID
    merchant_id: UUID
    connector_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SyncRequest(BaseModel):
    """Request schema for triggering a sync."""
    start_date: date
    end_date: date


class SyncResponse(BaseModel):
    """Response schema for sync results."""
    merchant_id: UUID
    source: str
    start_date: date
    end_date: date
    metrics_synced: int
    status: str


class SyncStatusResponse(BaseModel):
    """Response schema for last sync status."""
    merchant_id: UUID
    source: str
    last_sync_at: datetime | None
    total_metrics: int


# ── Route handlers ─────────────────────────────────────────────────────────


@router.post("/{merchant_id}/connectors", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def register_connector(
    merchant_id: UUID,
    data: ConnectorCreate,
    db: AsyncSession = Depends(get_db)
) -> ConnectorResponse:
    """
    Register a connector for a merchant.
    
    Returns:
        - 201: Connector registered successfully
        - 404: Merchant not found
        - 409: Connector already registered for this merchant
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
    
    # Check if connector already exists
    existing = await db.execute(
        select(MerchantConnector).where(
            MerchantConnector.merchant_id == merchant_id,
            MerchantConnector.connector_type == data.connector_type.value
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Connector {data.connector_type.value} already registered for merchant {merchant_id}"
        )
    
    # Create connector
    connector = MerchantConnector(
        merchant_id=merchant_id,
        connector_type=data.connector_type.value,
        config=data.config,
    )
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    
    return ConnectorResponse.model_validate(connector)


@router.get("/{merchant_id}/connectors", response_model=list[ConnectorResponse])
async def list_connectors(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> list[ConnectorResponse]:
    """
    List all connectors for a merchant.
    
    Returns:
        - 200: List of connectors
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
    
    # Get connectors
    result = await db.execute(
        select(MerchantConnector).where(MerchantConnector.merchant_id == merchant_id)
    )
    connectors = result.scalars().all()
    
    return [ConnectorResponse.model_validate(c) for c in connectors]


@router.post("/{merchant_id}/connectors/{source}/sync", response_model=SyncResponse)
async def sync_connector(
    merchant_id: UUID,
    source: Source,
    data: SyncRequest,
    db: AsyncSession = Depends(get_db)
) -> SyncResponse:
    """
    Trigger a sync for a specific connector.
    
    Loads connector config, fetches data from source API,
    normalizes it, and bulk upserts into metrics table.
    
    Returns:
        - 200: Sync completed successfully
        - 404: Merchant or connector not found
        - 500: Sync failed (API error, validation error, etc.)
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
    
    # Get connector config
    result = await db.execute(
        select(MerchantConnector).where(
            MerchantConnector.merchant_id == merchant_id,
            MerchantConnector.connector_type == source.value
        )
    )
    connector_config = result.scalar_one_or_none()
    
    if not connector_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector {source.value} not found for merchant {merchant_id}"
        )
    
    # Get connector class from registry
    try:
        connector_class = get_connector(source)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # Instantiate connector and sync
    try:
        connector = connector_class(
            merchant_id=merchant_id,
            config=connector_config.config
        )
        normalized_metrics = await connector.sync(
            start_date=data.start_date,
            end_date=data.end_date
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}"
        )
    
    # Bulk upsert metrics using INSERT ... ON CONFLICT DO NOTHING
    if normalized_metrics:
        values = [
            {
                "merchant_id": m.merchant_id,
                "source": m.source.value,
                "source_record_id": m.source_record_id,
                "metric_type": m.metric_type.value,
                "value": m.value,
                "currency": m.currency,
                "date": m.date,
                "dimensions": m.dimensions,
                "raw_data": m.raw_data,
                "fetched_at": m.fetched_at,
            }
            for m in normalized_metrics
        ]
        
        stmt = pg_insert(Metric).values(values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["merchant_id", "source", "source_record_id", "metric_type"]
        )
        await db.execute(stmt)
        await db.commit()
    
    return SyncResponse(
        merchant_id=merchant_id,
        source=source.value,
        start_date=data.start_date,
        end_date=data.end_date,
        metrics_synced=len(normalized_metrics),
        status="completed"
    )


@router.post("/{merchant_id}/connectors/demo/register")
async def register_demo_connectors(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Register demo connector configs for testing (without real API credentials).

    This endpoint registers all 3 connectors with placeholder/mock configs.
    Useful for testing the UI without needing real Shopify, Razorpay, or Meta Ads credentials.

    Returns:
        - 200: Demo connectors registered
        - 404: Merchant not found
        - 409: Connectors already registered
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

    # Demo configs
    demo_configs = {
        "shopify": {
            "store_url": "demo-store.myshopify.com",
            "access_token": "demo_token_placeholder"
        },
        "razorpay": {
            "key_id": "rzp_demo_key",
            "key_secret": "demo_secret_placeholder"
        },
        "meta_ads": {
            "access_token": "demo_token_placeholder",
            "ad_account_id": "act_demo123456"
        }
    }

    registered = []

    for source, config in demo_configs.items():
        # Check if already exists
        existing = await db.execute(
            select(MerchantConnector).where(
                MerchantConnector.merchant_id == merchant_id,
                MerchantConnector.connector_type == source
            )
        )

        if existing.scalar_one_or_none():
            continue  # Skip if already registered

        # Create connector
        connector = MerchantConnector(
            merchant_id=merchant_id,
            connector_type=source,
            config=config,
        )
        db.add(connector)
        registered.append(source)

    if registered:
        await db.commit()

    return {
        "merchant_id": str(merchant_id),
        "registered": registered,
        "message": f"Demo connectors registered: {', '.join(registered)}. Note: These are placeholder configs and cannot sync real data."
    }


@router.get("/{merchant_id}/connectors/{source}/status", response_model=SyncStatusResponse)
async def get_sync_status(
    merchant_id: UUID,
    source: Source,
    db: AsyncSession = Depends(get_db)
) -> SyncStatusResponse:
    """
    Get last sync status for a connector.
    
    Returns the last fetched_at timestamp and total metrics count.
    
    Returns:
        - 200: Status retrieved successfully
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
    
    # Get last sync time and total metrics
    from sqlalchemy import func
    result = await db.execute(
        select(
            func.max(Metric.fetched_at).label("last_sync_at"),
            func.count(Metric.id).label("total_metrics")
        ).where(
            Metric.merchant_id == merchant_id,
            Metric.source == source.value
        )
    )
    row = result.one()
    
    return SyncStatusResponse(
        merchant_id=merchant_id,
        source=source.value,
        last_sync_at=row.last_sync_at,
        total_metrics=row.total_metrics
    )
