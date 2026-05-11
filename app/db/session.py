from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields uma sessão async com commit/rollback automáticos."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
