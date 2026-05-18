"""
Merchant CRUD API routes.

Endpoints:
- POST /merchants — create merchant
- GET /merchants — list all active merchants
- GET /merchants/{merchant_id} — get single merchant
- PATCH /merchants/{merchant_id} — update name/email
- DELETE /merchants/{merchant_id} — soft delete (set is_active=False)
"""

from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel, EmailStr

from core.database import get_db
from models.merchant import Merchant


router = APIRouter(prefix="/merchants", tags=["merchants"])


# ── Pydantic schemas ───────────────────────────────────────────────────────


class MerchantCreate(BaseModel):
    """Request schema for creating a merchant."""
    name: str
    email: EmailStr


class MerchantUpdate(BaseModel):
    """Request schema for updating a merchant."""
    name: str | None = None
    email: EmailStr | None = None


class MerchantResponse(BaseModel):
    """Response schema for merchant data."""
    id: UUID
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Route handlers ─────────────────────────────────────────────────────────


@router.post("/", response_model=MerchantResponse, status_code=status.HTTP_201_CREATED)
async def create_merchant(
    data: MerchantCreate,
    db: AsyncSession = Depends(get_db)
) -> MerchantResponse:
    """
    Create a new merchant.
    
    Returns:
        - 201: Merchant created successfully
        - 409: Email already exists
    """
    # Check if email already exists
    existing = await db.execute(
        select(Merchant).where(Merchant.email == data.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Merchant with email {data.email} already exists"
        )
    
    # Create merchant
    merchant = Merchant(
        name=data.name,
        email=data.email,
    )
    db.add(merchant)
    await db.commit()
    await db.refresh(merchant)
    
    return MerchantResponse.model_validate(merchant)


@router.get("/", response_model=list[MerchantResponse])
async def list_merchants(
    db: AsyncSession = Depends(get_db)
) -> list[MerchantResponse]:
    """
    List all active merchants.
    
    Returns only merchants where is_active=True.
    """
    result = await db.execute(
        select(Merchant).where(Merchant.is_active == True).order_by(Merchant.created_at.desc())
    )
    merchants = result.scalars().all()
    
    return [MerchantResponse.model_validate(m) for m in merchants]


@router.get("/{merchant_id}", response_model=MerchantResponse)
async def get_merchant(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> MerchantResponse:
    """
    Get a single merchant by ID.
    
    Returns:
        - 200: Merchant found
        - 404: Merchant not found
    """
    result = await db.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()
    
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant {merchant_id} not found"
        )
    
    return MerchantResponse.model_validate(merchant)


@router.patch("/{merchant_id}", response_model=MerchantResponse)
async def update_merchant(
    merchant_id: UUID,
    data: MerchantUpdate,
    db: AsyncSession = Depends(get_db)
) -> MerchantResponse:
    """
    Update a merchant's name or email.
    
    Returns:
        - 200: Merchant updated successfully
        - 404: Merchant not found
        - 409: Email already exists (if changing email)
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
    
    # Check email uniqueness if changing email
    if data.email and data.email != merchant.email:
        existing = await db.execute(
            select(Merchant).where(Merchant.email == data.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Merchant with email {data.email} already exists"
            )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        await db.execute(
            update(Merchant)
            .where(Merchant.id == merchant_id)
            .values(**update_data)
        )
        await db.commit()
        await db.refresh(merchant)
    
    return MerchantResponse.model_validate(merchant)


@router.delete("/{merchant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_merchant(
    merchant_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> None:
    """
    Soft delete a merchant (set is_active=False).
    
    Returns:
        - 204: Merchant deleted successfully
        - 404: Merchant not found
    """
    result = await db.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    )
    merchant = result.scalar_one_or_none()
    
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant {merchant_id} not found"
        )
    
    # Soft delete
    await db.execute(
        update(Merchant)
        .where(Merchant.id == merchant_id)
        .values(is_active=False)
    )
    await db.commit()
