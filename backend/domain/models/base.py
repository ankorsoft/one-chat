"""
SQLAlchemy ORM Base class and common mixins.
All models inherit from Base for metadata management.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    declared_attr,
)


class Base(DeclarativeBase):
    """
    SQLAlchemy declarative base.
    All models should inherit from this class.
    """
    
    # Custom type annotations can be added here
    pass


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin for soft delete functionality."""
    
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    
    @declared_attr
    def is_deleted(cls) -> Mapped[bool]:
        return mapped_column(
            default=False,
            nullable=False,
        )


class SequenceIdMixin:
    """
    Mixin for strict message ordering.
    Uses bigint sequence_id for guaranteed ordering within workspace.
    """
    
    sequence_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )
    
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


def model_repr(model_class: type) -> str:
    """Generate a repr string for a SQLAlchemy model instance."""
    def __repr__(self) -> str:
        columns = []
        for col in self.__table__.columns:
            value = getattr(self, col.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, bytes):
                value = f"<{len(value)} bytes>"
            columns.append(f"{col.name}={value!r}")
        return f"<{model_class.__name__}({', '.join(columns)})>"
    
    return __repr__
