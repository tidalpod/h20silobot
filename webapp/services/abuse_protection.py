"""Database-backed throttling for public forms across all app replicas."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac

from sqlalchemy import delete, func, select

from database.connection import get_session
from database.models import PublicSubmissionAttempt
from webapp.config import web_config
from webapp.request_security import client_ip


async def check_and_record(request, event_type: str, limit: int, window_seconds: int) -> bool:
    """Record an attempt and return True when the origin is already over limit."""
    digest = hmac.new(
        web_config.secret_key.encode(),
        client_ip(request).encode(),
        hashlib.sha256,
    ).hexdigest()
    cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
    async with get_session() as session:
        await session.execute(delete(PublicSubmissionAttempt).where(
            PublicSubmissionAttempt.attempted_at < cutoff
        ))
        count = await session.scalar(select(func.count(PublicSubmissionAttempt.id)).where(
            PublicSubmissionAttempt.event_type == event_type,
            PublicSubmissionAttempt.key_hash == digest,
            PublicSubmissionAttempt.attempted_at >= cutoff,
        )) or 0
        session.add(PublicSubmissionAttempt(event_type=event_type, key_hash=digest))
        await session.commit()
    return count >= limit
