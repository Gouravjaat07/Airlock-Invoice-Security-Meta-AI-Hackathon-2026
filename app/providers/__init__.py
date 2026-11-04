"""Phase 3 provider package: secure multimodal model integrations.

All provider results are T2 (untrusted) and must pass the same local
validation as any other tainted input before reaching domain services.
"""

from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
    TaskKind,
    Usage,
    to_app_error,
)

__all__ = [
    "ProviderError",
    "ProviderErrorCategory",
    "ProviderName",
    "TaskKind",
    "Usage",
    "to_app_error",
]
