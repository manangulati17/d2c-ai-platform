from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Uses pydantic-settings to automatically load from .env file.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    # Environment
    ENV: str = "dev"
    
    # Database
    DATABASE_URL: str
    
    # OpenRouter (dev environment)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    # Azure OpenAI (prod environment)
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    
    # Shopify connector
    SHOPIFY_API_KEY: str = ""
    SHOPIFY_STORE_URL: str = ""
    
    # Razorpay connector
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    
    # Meta Ads connector
    META_ACCESS_TOKEN: str = ""
    META_AD_ACCOUNT_ID: str = ""
    
    # Celery / Redis
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"


# Global settings instance - import this everywhere
settings = Settings()
