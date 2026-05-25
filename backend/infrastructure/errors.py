"""
Unified error handling layer with retry logic and provider code mapping.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ErrorCategory(str, Enum):
    """Categories of errors for handling strategy."""
    
    VALIDATION = "validation"  # 4xx - client should fix request
    AUTHENTICATION = "authentication"  # 401 - re-authenticate
    AUTHORIZATION = "authorization"  # 403 - insufficient permissions
    NOT_FOUND = "not_found"  # 404 - resource doesn't exist
    RATE_LIMITED = "rate_limited"  # 429 - retry after delay
    CHANNEL_ERROR = "channel_error"  # External channel API error
    INTERNAL = "internal"  # 5xx - server error, retryable


@dataclass
class AppError(Exception):
    """
    Unified application error with metadata for retry logic and UI handling.
    """
    
    code: str
    message: str
    category: ErrorCategory
    is_retryable: bool = False
    retry_after: Optional[int] = None  # seconds to wait before retry
    mapped_provider_code: Optional[str] = None  # original provider error code
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API response."""
        return {
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "is_retryable": self.is_retryable,
            "retry_after": self.retry_after,
            "mapped_provider_code": self.mapped_provider_code,
            "details": self.details,
        }


# Predefined error codes
class ErrorCodes:
    """Standardized error codes across the application."""
    
    # Authentication
    INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    REFRESH_TOKEN_REVOKED = "AUTH_REFRESH_REVOKED"
    
    # Authorization
    FORBIDDEN = "AUTH_FORBIDDEN"
    WORKSPACE_ACCESS_DENIED = "WORKSPACE_ACCESS_DENIED"
    ROLE_INSUFFICIENT = "ROLE_INSUFFICIENT"
    
    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_PHONE_NUMBER = "VALIDATION_INVALID_PHONE"
    INVALID_CHANNEL_CONFIG = "VALIDATION_INVALID_CHANNEL"
    
    # Not Found
    USER_NOT_FOUND = "USER_NOT_FOUND"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    MESSAGE_NOT_FOUND = "MESSAGE_NOT_FOUND"
    CHANNEL_ACCOUNT_NOT_FOUND = "CHANNEL_ACCOUNT_NOT_FOUND"
    
    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CHANNEL_RATE_LIMITED = "CHANNEL_RATE_LIMITED"
    
    # Channel Errors
    CHANNEL_SEND_FAILED = "CHANNEL_SEND_FAILED"
    CHANNEL_WEBHOOK_INVALID = "CHANNEL_WEBHOOK_INVALID"
    CHANNEL_SIGNATURE_INVALID = "CHANNEL_SIGNATURE_INVALID"
    CHANNEL_TEMPLATE_REJECTED = "CHANNEL_TEMPLATE_REJECTED"
    CHANNEL_24H_WINDOW_CLOSED = "CHANNEL_24H_WINDOW_CLOSED"
    
    # Media
    MEDIA_UPLOAD_FAILED = "MEDIA_UPLOAD_FAILED"
    MEDIA_VIRUS_DETECTED = "MEDIA_VIRUS_DETECTED"
    MEDIA_TOO_LARGE = "MEDIA_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    
    # Internal
    DATABASE_ERROR = "DATABASE_ERROR"
    REDIS_ERROR = "REDIS_ERROR"
    S3_ERROR = "S3_ERROR"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# Factory functions for common errors
def validation_error(message: str, details: Optional[Dict[str, Any]] = None) -> AppError:
    """Create a validation error."""
    return AppError(
        code=ErrorCodes.VALIDATION_ERROR,
        message=message,
        category=ErrorCategory.VALIDATION,
        is_retryable=False,
        details=details or {},
    )


def authentication_error(message: str) -> AppError:
    """Create an authentication error."""
    return AppError(
        code=ErrorCodes.TOKEN_INVALID,
        message=message,
        category=ErrorCategory.AUTHENTICATION,
        is_retryable=False,
    )


def authorization_error(message: str) -> AppError:
    """Create an authorization error."""
    return AppError(
        code=ErrorCodes.FORBIDDEN,
        message=message,
        category=ErrorCategory.AUTHORIZATION,
        is_retryable=False,
    )


def not_found_error(resource: str, identifier: str) -> AppError:
    """Create a not found error."""
    return AppError(
        code=f"{resource.upper()}_NOT_FOUND",
        message=f"{resource} '{identifier}' not found",
        category=ErrorCategory.NOT_FOUND,
        is_retryable=False,
        details={"resource": resource, "identifier": identifier},
    )


def rate_limit_error(retry_after: int, channel_type: Optional[str] = None) -> AppError:
    """Create a rate limit error."""
    code = (
        ErrorCodes.CHANNEL_RATE_LIMITED
        if channel_type
        else ErrorCodes.RATE_LIMIT_EXCEEDED
    )
    message = (
        f"Rate limit exceeded for {channel_type}"
        if channel_type
        else "Rate limit exceeded"
    )
    return AppError(
        code=code,
        message=message,
        category=ErrorCategory.RATE_LIMITED,
        is_retryable=True,
        retry_after=retry_after,
        details={"channel_type": channel_type} if channel_type else {},
    )


def channel_error(
    message: str,
    provider_code: Optional[str] = None,
    is_retryable: bool = False,
    retry_after: Optional[int] = None,
) -> AppError:
    """Create a channel provider error."""
    return AppError(
        code=ErrorCodes.CHANNEL_SEND_FAILED,
        message=message,
        category=ErrorCategory.CHANNEL_ERROR,
        is_retryable=is_retryable,
        retry_after=retry_after,
        mapped_provider_code=provider_code,
    )


def internal_error(message: str, retryable: bool = True) -> AppError:
    """Create an internal server error."""
    return AppError(
        code=ErrorCodes.INTERNAL_SERVER_ERROR,
        message=message,
        category=ErrorCategory.INTERNAL,
        is_retryable=retryable,
    )
