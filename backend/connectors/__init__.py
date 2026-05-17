from connectors.base import BaseConnector
from connectors.registry import (
    register,
    get_connector,
    list_registered_sources,
    is_registered,
)

# Import connectors to trigger self-registration
from connectors.shopify import ShopifyConnector
from connectors.razorpay import RazorpayConnector
from connectors.meta_ads import MetaAdsConnector

__all__ = [
    "BaseConnector",
    "register",
    "get_connector",
    "list_registered_sources",
    "is_registered",
    "ShopifyConnector",
    "RazorpayConnector",
    "MetaAdsConnector",
]
