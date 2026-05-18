"""
Citation enforcement for chat responses.

Every numerical claim must trace back to source metric row IDs.
This module provides:
1. Citation extraction from LLM responses
2. Citation validation against the database
3. Citation formatting utilities

Citation format: "Value [cited: uuid1, uuid2, ...]"
Example: "Total revenue was $5,000 [cited: 123e4567-e89b-12d3-a456-426614174000]"
"""

import re
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.metrics import Metric


# Citation pattern: [cited: uuid1, uuid2, ...]
CITATION_PATTERN = re.compile(
    r'\[cited:\s*([a-f0-9\-,\s]+)\]',
    re.IGNORECASE
)

# Number pattern: currency symbols, numbers with commas/decimals, percentages
NUMBER_PATTERN = re.compile(
    r'(?:[$₹€£¥]|INR|USD|EUR)?\s*[\d,]+\.?\d*\s*%?'
)


def extract_citations(text: str) -> list[str]:
    """
    Extract all cited row IDs from text.
    
    Args:
        text: Response text with citations
    
    Returns:
        List of row ID strings (UUIDs)
    
    Example:
        >>> extract_citations("Revenue was $5k [cited: abc-123, def-456]")
        ['abc-123', 'def-456']
    """
    citations = []
    
    for match in CITATION_PATTERN.finditer(text):
        # Extract UUIDs from the match
        uuid_string = match.group(1)
        # Split by comma and strip whitespace
        uuids = [uid.strip() for uid in uuid_string.split(',')]
        citations.extend(uuids)
    
    return citations


def extract_numbers(text: str) -> list[str]:
    """
    Extract all number-like strings from text.
    
    Args:
        text: Text to search for numbers
    
    Returns:
        List of number strings found
    
    Example:
        >>> extract_numbers("Revenue was $5,000 and ROAS was 2.5x")
        ['$5,000', '2.5']
    """
    return NUMBER_PATTERN.findall(text)


def has_citation_for_number(text_before_number: str, text_after_number: str) -> bool:
    """
    Check if a number has a citation nearby (within 100 characters).
    
    Args:
        text_before_number: Text before the number
        text_after_number: Text after the number
    
    Returns:
        True if citation found nearby
    """
    context = text_before_number[-100:] + text_after_number[:100]
    return bool(CITATION_PATTERN.search(context))


def validate_citation_coverage(text: str, strict: bool = False) -> dict[str, Any]:
    """
    Validate that numbers in text have citation coverage.
    
    Args:
        text: Response text to validate
        strict: If True, every number must have a citation
    
    Returns:
        {
            "valid": bool,
            "numbers_found": int,
            "citations_found": int,
            "cited_row_ids": list[str],
            "issues": list[str]
        }
    """
    numbers = extract_numbers(text)
    citations = extract_citations(text)
    issues = []
    
    # Check if we have citations
    if not citations and numbers:
        issues.append("Found numbers but no citations in response")
    
    if strict and len(citations) == 0 and len(numbers) > 0:
        issues.append(f"Strict mode: {len(numbers)} numbers found but 0 citations")
    
    return {
        "valid": len(issues) == 0,
        "numbers_found": len(numbers),
        "citations_found": len(citations),
        "cited_row_ids": citations,
        "issues": issues
    }


async def verify_citations_exist(
    cited_row_ids: list[str],
    merchant_id: UUID,
    db: AsyncSession
) -> dict[str, Any]:
    """
    Verify that cited row IDs actually exist in the database for this merchant.
    
    Args:
        cited_row_ids: List of row ID strings to verify
        merchant_id: Merchant ID for security check
        db: Database session
    
    Returns:
        {
            "valid": bool,
            "found_count": int,
            "missing_count": int,
            "missing_ids": list[str],
            "metrics": list[dict]  # Brief info about found metrics
        }
    """
    if not cited_row_ids:
        return {
            "valid": True,
            "found_count": 0,
            "missing_count": 0,
            "missing_ids": [],
            "metrics": []
        }
    
    # Convert string IDs to UUIDs
    try:
        uuid_ids = [UUID(rid) for rid in cited_row_ids]
    except ValueError as e:
        return {
            "valid": False,
            "error": f"Invalid UUID format: {str(e)}",
            "found_count": 0,
            "missing_count": len(cited_row_ids),
            "missing_ids": cited_row_ids,
            "metrics": []
        }
    
    # Query database
    query = select(Metric).where(
        Metric.id.in_(uuid_ids),
        Metric.merchant_id == merchant_id
    )
    result = await db.execute(query)
    found_metrics = result.scalars().all()
    
    found_ids = {str(m.id) for m in found_metrics}
    missing_ids = [rid for rid in cited_row_ids if rid not in found_ids]
    
    # Build metric info
    metrics_info = [
        {
            "id": str(m.id),
            "source": m.source,
            "metric_type": m.metric_type,
            "value": float(m.value),
            "currency": m.currency,
            "date": m.date.isoformat()
        }
        for m in found_metrics
    ]
    
    return {
        "valid": len(missing_ids) == 0,
        "found_count": len(found_metrics),
        "missing_count": len(missing_ids),
        "missing_ids": missing_ids,
        "metrics": metrics_info
    }


def format_citation(row_ids: list[str]) -> str:
    """
    Format a citation string from row IDs.
    
    Args:
        row_ids: List of row ID strings
    
    Returns:
        Formatted citation string
    
    Example:
        >>> format_citation(["abc-123", "def-456"])
        "[cited: abc-123, def-456]"
    """
    if not row_ids:
        return ""
    
    return f"[cited: {', '.join(row_ids)}]"


def add_citation_to_claim(claim: str, row_ids: list[str]) -> str:
    """
    Add citation to a claim if not already present.
    
    Args:
        claim: The claim text (e.g., "Total revenue was $5,000")
        row_ids: List of row IDs to cite
    
    Returns:
        Claim with citation appended
    
    Example:
        >>> add_citation_to_claim("Total revenue was $5,000", ["abc-123"])
        "Total revenue was $5,000 [cited: abc-123]"
    """
    # Check if already has citation
    if CITATION_PATTERN.search(claim):
        return claim
    
    citation = format_citation(row_ids)
    return f"{claim.rstrip()} {citation}"


async def validate_full_response(
    response_text: str,
    merchant_id: UUID,
    db: AsyncSession,
    strict: bool = False
) -> dict[str, Any]:
    """
    Complete validation of a chat response: coverage + existence.
    
    Args:
        response_text: The assistant's response
        merchant_id: Merchant ID for database verification
        db: Database session
        strict: If True, every number must have a citation
    
    Returns:
        {
            "valid": bool,
            "coverage": dict,  # Result from validate_citation_coverage
            "verification": dict,  # Result from verify_citations_exist
            "summary": str
        }
    """
    # Check coverage
    coverage = validate_citation_coverage(response_text, strict=strict)
    
    # Verify existence
    verification = await verify_citations_exist(
        cited_row_ids=coverage["cited_row_ids"],
        merchant_id=merchant_id,
        db=db
    )
    
    # Overall validity
    valid = coverage["valid"] and verification["valid"]
    
    # Summary
    if valid:
        summary = f"✓ Valid: {coverage['citations_found']} citations for {coverage['numbers_found']} numbers, all verified in database"
    else:
        issues = coverage["issues"] + verification.get("missing_ids", [])
        summary = f"✗ Invalid: {len(issues)} issues found"
    
    return {
        "valid": valid,
        "coverage": coverage,
        "verification": verification,
        "summary": summary
    }


# ============================================================================
# Citation decorator for tool results
# ============================================================================

def attach_citations_to_tool_result(tool_result: dict[str, Any]) -> str:
    """
    Convert a tool result dict into a citation-annotated string for LLM context.
    
    This helps the LLM see the row IDs it needs to cite when making claims
    based on tool results.
    
    Args:
        tool_result: Dict from a tool execution
    
    Returns:
        Formatted string with embedded citations
    
    Example:
        >>> result = {"result": 5000, "currency": "INR", "cited_row_ids": ["abc", "def"]}
        >>> attach_citations_to_tool_result(result)
        "Result: 5000 INR [cited: abc, def]"
    """
    lines = []
    
    # Handle different tool result formats
    if "result" in tool_result:
        # Aggregate result
        value = tool_result["result"]
        currency = tool_result.get("currency", "")
        row_ids = tool_result.get("cited_row_ids", [])
        
        lines.append(f"Result: {value} {currency} {format_citation(row_ids)}")
    
    elif "timeseries" in tool_result:
        # Time series result
        for point in tool_result["timeseries"]:
            date = point["date"]
            value = point["value"]
            row_ids = point.get("cited_row_ids", [])
            currency = tool_result.get("currency", "")
            
            lines.append(f"{date}: {value} {currency} {format_citation(row_ids)}")
    
    elif "breakdown" in tool_result:
        # Breakdown result
        for item in tool_result["breakdown"]:
            dim_value = item["dimension_value"]
            value = item["value"]
            row_ids = item.get("cited_row_ids", [])
            currency = tool_result.get("currency", "")
            
            lines.append(f"{dim_value}: {value} {currency} {format_citation(row_ids)}")
    
    elif "roas" in tool_result:
        # ROAS result
        roas = tool_result["roas"]
        revenue = tool_result["revenue"]
        ad_spend = tool_result["ad_spend"]
        revenue_ids = tool_result.get("revenue_cited_row_ids", [])
        ad_spend_ids = tool_result.get("ad_spend_cited_row_ids", [])
        
        lines.append(f"ROAS: {roas:.2f}")
        lines.append(f"Revenue: {revenue} {format_citation(revenue_ids)}")
        lines.append(f"Ad Spend: {ad_spend} {format_citation(ad_spend_ids)}")
    
    return "\n".join(lines) if lines else str(tool_result)
