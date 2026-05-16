from openai import AsyncOpenAI, AsyncAzureOpenAI
import httpx
from typing import Optional

from core.config import settings


class LLMClient:
    """
    Unified LLM client abstraction that switches between OpenRouter (dev) and Azure OpenAI (prod).
    Callers use the same interface regardless of which provider is active.
    """
    
    def __init__(self):
        http_client = httpx.AsyncClient()
        
        if settings.ENV == "dev":
            # OpenRouter (dev environment)
            self.client = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=settings.OPENROUTER_BASE_URL,
                http_client=http_client,
            )
            self.model = "anthropic/claude-sonnet-4"
        else:
            # Azure OpenAI (prod environment)
            self.client = AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version="2024-02-15-preview",
                http_client=http_client,
            )
            self.model = settings.AZURE_OPENAI_DEPLOYMENT
    
    async def chat(self, messages: list, tools: Optional[list] = None) -> dict:
        """
        Send a chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool/function definitions for function calling
        
        Returns:
            Dict containing the completion response
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
        }
        
        if tools:
            kwargs["tools"] = tools
        
        response = await self.client.chat.completions.create(**kwargs)
        
        return response.model_dump()


# Global LLM client instance - import this everywhere
llm_client = LLMClient()
