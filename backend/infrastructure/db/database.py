"""
Database configuration and session management.
SQLAlchemy 2.0 async with UnitOfWork pattern for atomic operations.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
    AsyncEngine,
)
from sqlalchemy.pool import NullPool

from backend.infrastructure.config import get_settings


class DatabaseManager:
    """
    Manages database connections and sessions.
    Implements UnitOfWork pattern for atomic transactions.
    """
    
    _instance: Optional["DatabaseManager"] = None
    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    
    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        settings = get_settings()
        
        self._engine = create_async_engine(
            settings.database.database_url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout,
            pool_recycle=settings.database.pool_recycle,
            pool_pre_ping=True,  # Verify connections before use
            echo=settings.debug,  # Log SQL in debug mode
        )
        
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        
        self._initialized = True
    
    @property
    def engine(self) -> AsyncEngine:
        """Get the async engine."""
        if self._engine is None:
            raise RuntimeError("Database not initialized")
        return self._engine
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session.
        Use as context manager for automatic rollback on exception.
        
        Example:
            async with db_manager.session() as session:
                # do work
                await session.commit()
        """
        session = self._session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    @asynccontextmanager
    async def unit_of_work(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Unit of Work context manager for atomic operations.
        Automatically commits on success, rolls back on failure.
        
        Example:
            async with db_manager.unit_of_work() as session:
                # All operations here are atomic
                session.add(entity1)
                session.add(entity2)
                # commit happens automatically on exit
        """
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def create_tables(self) -> None:
        """Create all tables (for testing/development)."""
        from backend.domain.models.base import Base
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def drop_tables(self) -> None:
        """Drop all tables (for testing)."""
        from backend.domain.models.base import Base
        
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    
    async def close(self) -> None:
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()


# Global instance
_db_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """Get the global database manager singleton."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def set_database_manager(manager: DatabaseManager) -> None:
    """Set the database manager (for testing)."""
    global _db_manager
    _db_manager = manager


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI routes.
    Provides a session with automatic cleanup.
    """
    db_manager = get_database_manager()
    async with db_manager.session() as session:
        yield session


@asynccontextmanager
async def get_unit_of_work() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI routes requiring atomic operations.
    """
    db_manager = get_database_manager()
    async with db_manager.unit_of_work() as session:
        yield session
