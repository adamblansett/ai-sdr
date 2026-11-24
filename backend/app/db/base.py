import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base class."""


def new_uuid() -> str:
    """Generate a string UUID4 identifier."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def as_utc(dt: datetime) -> datetime:
    """Normalize naive or tz-aware datetimes into UTC for safe arithmetic."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    """Normalize currency amounts to two decimal places with half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
