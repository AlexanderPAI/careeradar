import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import cfg
from backend.db.models import CandidateProfile

UPLOAD_DIR = Path("backend/storage/cv")


def ensure_private_storage() -> None:
    """Create the resume directory and repair permissions of existing content."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    UPLOAD_DIR.chmod(0o700)
    for path in UPLOAD_DIR.iterdir():
        if path.is_file():
            path.chmod(0o600)


def save_upload(file: UploadFile, filename: str) -> Path:
    ensure_private_storage()
    path = (UPLOAD_DIR / filename).resolve()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            shutil.copyfileobj(file.file, destination)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def delete_resume_file(path_value: str | None) -> None:
    if not path_value:
        return
    storage_root = UPLOAD_DIR.resolve()
    path = Path(path_value).resolve()
    try:
        path.relative_to(storage_root)
    except ValueError:
        return
    path.unlink(missing_ok=True)


def expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=cfg.resume_retention_days)


async def purge_expired_resumes(session: AsyncSession) -> int:
    """Erase expired originals and extracted text while preserving profiles."""
    now = datetime.now(timezone.utc)
    profiles = (
        await session.scalars(
            select(CandidateProfile).where(
                CandidateProfile.resume_expires_at.is_not(None),
                CandidateProfile.resume_expires_at <= now,
            )
        )
    ).all()
    for profile in profiles:
        delete_resume_file(profile.source_path)
        profile.source_path = None
        profile.cv_text = None
        profile.resume_expires_at = None

    cutoff = now - timedelta(days=cfg.resume_retention_days)
    ensure_private_storage()
    linked_paths = {
        str(Path(value).resolve())
        for value in (
            await session.scalars(
                select(CandidateProfile.source_path).where(
                    CandidateProfile.source_path.is_not(None)
                )
            )
        ).all()
        if value
    }
    for path in UPLOAD_DIR.iterdir():
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if (
            path.is_file()
            and str(path.resolve()) not in linked_paths
            and modified_at <= cutoff
        ):
            path.unlink(missing_ok=True)

    if profiles:
        await session.commit()
    return len(profiles)
