"""
Chat API routes.

Endpoints:
- POST /chat — send a message, get a response with citations
"""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db
from models.merchant import Merchant
from chat.loop import chat_with_tools, get_default_system_prompt
from chat.citations import validate_full_response, extract_citations


router = APIRouter(prefix="/chat", tags=["chat"])


# ── Pydantic schemas ───────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Request schema for chat endpoint."""
    message: str
    merchant_id: UUID
    conversation_history: list[dict] | None = None


class ChatResponse(BaseModel):
    """Response schema for chat endpoint."""
    assistant_message: str
    tool_calls: list[dict]
    cited_row_ids: list[str]
    citation_valid: bool
    citation_errors: list[str] | None
    iteration_count: int


# ── Route handlers ─────────────────────────────────────────────────────────


@router.post("/", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    db: AsyncSession = Depends(get_db)
) -> ChatResponse:
    """
    Send a chat message and receive a response with citations.
    
    The assistant will use tools to query the metrics database
    and cite all numerical claims back to source rows.
    
    Returns:
        - 200: Response generated successfully
        - 400: Merchant not found or invalid request
        - 500: Chat processing failed
    """
    # Check merchant exists
    result = await db.execute(
        select(Merchant).where(Merchant.id == data.merchant_id)
    )
    merchant = result.scalar_one_or_none()
    
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Merchant {data.merchant_id} not found"
        )
    
    # Build conversation history:
    # 1. Always start with system prompt (includes today's date for relative queries)
    # 2. Strip any system messages from client-supplied history (prompt injection guard)
    history = [{"role": "system", "content": get_default_system_prompt()}]
    if data.conversation_history:
        history.extend(
            msg for msg in data.conversation_history
            if msg.get("role") != "system"
        )

    # Execute chat with tools
    try:
        chat_result = await chat_with_tools(
            user_message=data.message,
            merchant_id=data.merchant_id,
            db=db,
            conversation_history=history
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat processing failed: {str(e)}"
        )
    
    assistant_message = chat_result["assistant_message"]
    
    # Extract citations from response
    cited_row_ids = extract_citations(assistant_message)
    
    # Validate citations
    validation_result = await validate_full_response(
        response_text=assistant_message,
        merchant_id=data.merchant_id,
        db=db
    )
    
    # Flatten errors from the nested structure validate_full_response returns:
    # coverage["issues"] holds coverage problems, verification["missing_ids"] holds bad UUIDs
    citation_errors = (
        validation_result["coverage"]["issues"]
        + validation_result["verification"].get("missing_ids", [])
    ) or None

    return ChatResponse(
        assistant_message=assistant_message,
        tool_calls=chat_result["tool_calls"],
        cited_row_ids=[str(cid) for cid in cited_row_ids],
        citation_valid=validation_result["valid"],
        citation_errors=citation_errors,
        iteration_count=chat_result["iteration_count"]
    )
