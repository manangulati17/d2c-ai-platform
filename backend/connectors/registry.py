from typing import Type

from connectors.base import BaseConnector
from models.enums import Source


# Global registry mapping Source enum values to connector classes
_REGISTRY: dict[Source, Type[BaseConnector]] = {}


def register(cls: Type[BaseConnector]) -> Type[BaseConnector]:
    """
    Decorator to self-register a connector class.

    Each connector file imports this and decorates its class:
        @register
        class ShopifyConnector(BaseConnector):
            source = Source.SHOPIFY
            ...

    The connector is automatically added to the registry when the module
    is imported. Adding a 4th connector requires no changes to sync jobs
    or API routes — just create the file and import it in __init__.py.

    Args:
        cls: The connector class to register.

    Returns:
        The same class, unchanged (passes through for decorator pattern).

    Raises:
        ValueError: If source is None or already registered.
    """
    if cls.source is None:
        raise ValueError(
            f"{cls.__name__} cannot be registered: "
            f"'source' class variable is None"
        )

    if cls.source in _REGISTRY:
        existing = _REGISTRY[cls.source]
        raise ValueError(
            f"Source {cls.source.value!r} already registered by "
            f"{existing.__name__}. Cannot register {cls.__name__}."
        )

    _REGISTRY[cls.source] = cls
    return cls


def get_connector(source: Source) -> Type[BaseConnector]:
    """
    Look up a connector class by its Source enum value.

    Usage in sync jobs and API routes:
        ConnectorClass = get_connector(Source.SHOPIFY)
        connector = ConnectorClass(merchant_id, config)
        rows = await connector.sync(start_date, end_date)

    Args:
        source: The Source enum value to look up.

    Returns:
        The registered connector class for this source.

    Raises:
        ValueError: If no connector is registered for this source.
    """
    if source not in _REGISTRY:
        registered = [s.value for s in _REGISTRY.keys()]
        raise ValueError(
            f"No connector registered for source {source.value!r}. "
            f"Registered sources: {registered}"
        )
    return _REGISTRY[source]


def list_registered_sources() -> list[Source]:
    """
    Return all Source enum values that have registered connectors.

    Useful for UI dropdowns, admin panels, and debugging.
    """
    return sorted(_REGISTRY.keys(), key=lambda s: s.value)


def is_registered(source: Source) -> bool:
    """Check if a connector is registered for the given source."""
    return source in _REGISTRY
