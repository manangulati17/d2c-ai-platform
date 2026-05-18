"""
Tool-use loop for chat interface.

The loop:
1. Receives user message
2. Sends to LLM with tool definitions
3. If LLM calls a tool, executes it and feeds result back
4. Repeats until LLM produces a final text response
5. Returns complete conversation with citations

Multi-tenancy: Every tool call is scoped to merchant_id.
"""

from datetime import date
from typing import Any
from uuid import UUID
import json
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm import llm_client
from chat.tools import TOOL_DEFINITIONS, execute_tool


MAX_TOOL_ITERATIONS = 10  # Prevent infinite loops


async def chat_with_tools(
    user_message: str,
    merchant_id: UUID,
    db: AsyncSession,
    conversation_history: list[dict] | None = None
) -> dict[str, Any]:
    """
    Execute a chat conversation with tool-use loop.
    
    Args:
        user_message: The user's question
        merchant_id: Merchant ID for data filtering
        db: Database session for tool execution
        conversation_history: Optional prior conversation history
    
    Returns:
        {
            "assistant_message": <final LLM response text>,
            "tool_calls": [<list of tool calls made>],
            "conversation": [<complete message history>],
            "iteration_count": <number of tool-use iterations>
        }
    """
    # Initialize conversation
    if conversation_history is None:
        conversation_history = []
    
    # Add user message
    conversation_history.append({
        "role": "user",
        "content": user_message
    })
    
    tool_calls_log = []
    iteration = 0
    
    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        
        # Call LLM with current conversation and tool definitions
        response = await llm_client.chat(
            messages=conversation_history,
            tools=TOOL_DEFINITIONS
        )
        
        # Extract assistant message from response
        assistant_message = response["choices"][0]["message"]
        
        # Check if assistant wants to call tools
        tool_calls = assistant_message.get("tool_calls")
        
        if not tool_calls:
            # No tool calls - we have a final response
            conversation_history.append({
                "role": "assistant",
                "content": assistant_message.get("content", "")
            })
            
            return {
                "assistant_message": assistant_message.get("content", ""),
                "tool_calls": tool_calls_log,
                "conversation": conversation_history,
                "iteration_count": iteration
            }
        
        # Assistant wants to call tools - add its message to history
        conversation_history.append(assistant_message)
        
        # Execute each tool call
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args_str = tool_call["function"]["arguments"]
            tool_call_id = tool_call["id"]
            
            # Parse arguments
            try:
                tool_args = json.loads(tool_args_str)
            except json.JSONDecodeError as e:
                # Invalid JSON arguments
                tool_result = {
                    "error": f"Invalid JSON arguments: {str(e)}"
                }
            else:
                # Execute tool
                try:
                    tool_result = await execute_tool(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        db=db,
                        merchant_id=merchant_id
                    )
                except Exception as e:
                    # Tool execution error
                    tool_result = {
                        "error": f"Tool execution failed: {str(e)}"
                    }
            
            # Log tool call
            tool_calls_log.append({
                "tool_name": tool_name,
                "tool_args": tool_args if isinstance(tool_args_str, dict) else tool_args_str,
                "tool_result": tool_result
            })
            
            # Add tool result to conversation
            conversation_history.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": json.dumps(tool_result)
            })
        
        # Loop continues - LLM will see tool results and respond
    
    # Max iterations reached - return what we have
    return {
        "assistant_message": "I apologize, but I reached the maximum number of tool calls. Please try rephrasing your question.",
        "tool_calls": tool_calls_log,
        "conversation": conversation_history,
        "iteration_count": iteration,
        "error": "max_iterations_reached"
    }


async def chat_simple(
    user_message: str,
    merchant_id: UUID,
    db: AsyncSession
) -> str:
    """
    Simplified chat interface that returns just the assistant's final message.
    
    Args:
        user_message: The user's question
        merchant_id: Merchant ID for data filtering
        db: Database session for tool execution
    
    Returns:
        The assistant's final response text
    """
    result = await chat_with_tools(user_message, merchant_id, db)
    return result["assistant_message"]


async def chat_with_context(
    user_message: str,
    merchant_id: UUID,
    db: AsyncSession,
    system_prompt: str | None = None
) -> dict[str, Any]:
    """
    Chat with optional system prompt for context.
    
    Args:
        user_message: The user's question
        merchant_id: Merchant ID for data filtering
        db: Database session for tool execution
        system_prompt: Optional system message to set context
    
    Returns:
        Complete chat result with tool calls and conversation
    """
    conversation = []
    
    if system_prompt:
        conversation.append({
            "role": "system",
            "content": system_prompt
        })
    
    return await chat_with_tools(
        user_message=user_message,
        merchant_id=merchant_id,
        db=db,
        conversation_history=conversation
    )


def get_default_system_prompt(today: date | None = None) -> str:
    """Build the chat system prompt with the current date for relative time queries."""
    today = today or date.today()
    today_iso = today.isoformat()
    return f"""You are a data analyst assistant for a D2C e-commerce business.

Today's date is {today_iso}. Use this when interpreting relative time references
(e.g. "this month", "last week", "today", "yesterday") and when choosing tool date ranges.

You have access to tools that query data from three sources:
- Shopify (orders, revenue, products)
- Razorpay (payments, settlements, refunds)
- Meta Ads (ad spend, campaigns, conversions)

CRITICAL CITATION RULE:
Every numerical claim you make MUST include the metric row IDs that support it.
Format: "Total revenue was $5,000 [cited: row_id_1, row_id_2, ...]"

When using tools:
- Always specify date ranges explicitly
- Use ISO date format (YYYY-MM-DD)
- Break complex questions into multiple tool calls if needed
- Cross-reference data between sources when answering attribution questions

Be concise and data-driven. Always cite your sources.
"""
