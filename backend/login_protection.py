import asyncio
import hashlib
import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import cfg
from backend.db.models import LoginAttempt


def normalize_username(username: str) -> str:
    return username.strip().lower()[:150]


def client_ip(request: Request) -> str:
    """Use the direct peer address; forwarded headers are untrusted by default."""
    host = request.client.host if request.client else "unknown"
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return "unknown"


def _advisory_lock_key(scope: str, value: str) -> int:
    digest = hashlib.blake2b(f"{scope}:{value}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, signed=True)


async def lock_attempt_buckets(
    session: AsyncSession, username: str, ip_address: str
) -> None:
    """Serialize attempts for both buckets across all application workers."""
    keys = sorted(
        (
            _advisory_lock_key("ip", ip_address),
            _advisory_lock_key("username", username),
        )
    )
    for key in keys:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def recent_failure_counts(
    session: AsyncSession, username: str, ip_address: str
) -> tuple[int, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=cfg.auth_rate_limit_window_seconds
    )
    username_count = await session.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.username == username,
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    ip_count = await session.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.client_ip == ip_address,
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    return int(username_count or 0), int(ip_count or 0)


def is_rate_limited(username_failures: int, ip_failures: int) -> bool:
    return (
        username_failures >= cfg.auth_rate_limit_username_attempts
        or ip_failures >= cfg.auth_rate_limit_ip_attempts
    )


async def audit_failure(
    session: AsyncSession,
    *,
    username: str,
    ip_address: str,
    reason: str,
) -> None:
    session.add(
        LoginAttempt(
            username=username,
            client_ip=ip_address,
            reason=reason,
        )
    )
    await session.commit()


async def failure_delay(previous_failures: int) -> None:
    exponent = min(previous_failures, 4)
    delay = min(
        cfg.auth_failure_delay_base_seconds * (2**exponent),
        cfg.auth_failure_delay_max_seconds,
    )
    await asyncio.sleep(delay)
