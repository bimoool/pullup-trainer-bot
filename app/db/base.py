from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# SQLAlchemy exceptions are logged and may be forwarded to admin notifications.
# Bound values can contain profile data and private workout/support notes.
engine = create_async_engine(settings.database_url, hide_parameters=True)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
