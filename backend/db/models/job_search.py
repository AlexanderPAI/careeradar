import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.models.base import Base

if TYPE_CHECKING:
    from backend.db.models.resume_recommendation import ResumeRecommendation
    from backend.db.models.user import User


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(255))
    target_positions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list)
    experience_years: Mapped[float | None] = mapped_column(Float)
    experience_level: Mapped[str | None] = mapped_column(String(32))
    salary_expectation: Mapped[int | None] = mapped_column(Integer)
    preferred_schedule: Mapped[str | None] = mapped_column(String(32))
    preferred_employment: Mapped[str | None] = mapped_column(String(32))
    location: Mapped[str | None] = mapped_column(String(255))
    industries: Mapped[list[str]] = mapped_column(JSONB, default=list)
    languages: Mapped[list[str]] = mapped_column(JSONB, default=list)
    education: Mapped[list[str]] = mapped_column(JSONB, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    search_prompt: Mapped[str | None] = mapped_column(Text)
    source_filename: Mapped[str | None] = mapped_column(String(512))
    source_path: Mapped[str | None] = mapped_column(String(1024))
    cv_text: Mapped[str | None] = mapped_column(Text)
    resume_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    searches: Mapped[list["SearchRun"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    resume_recommendations: Mapped[list["ResumeRecommendation"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    owner: Mapped["User"] = relationship(back_populates="profiles")


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    queries: Mapped[list[str]] = mapped_column(JSONB, default=list)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    area: Mapped[int] = mapped_column(Integer, default=1)
    max_pages: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    total_found: Mapped[int] = mapped_column(Integer, default=0)
    relevant_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    filtered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[CandidateProfile | None] = relationship(back_populates="searches")
    owner: Mapped["User"] = relationship(back_populates="searches")
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="search_run",
        cascade="all, delete-orphan",
        order_by="SearchResult.position",
    )


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(String(1024))
    company: Mapped[str | None] = mapped_column(String(512))
    salary_text: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    schedule: Mapped[str | None] = mapped_column(String(255))
    experience: Mapped[str | None] = mapped_column(String(255))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    search_results: Mapped[list["SearchResult"]] = relationship(
        back_populates="vacancy"
    )


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (UniqueConstraint("search_run_id", "vacancy_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_runs.id", ondelete="CASCADE"), index=True
    )
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), index=True
    )
    query: Mapped[str | None] = mapped_column(String(1024))
    position: Mapped[int] = mapped_column(Integer)
    is_relevant: Mapped[bool | None] = mapped_column(Boolean, index=True)
    filter_details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="results")
    vacancy: Mapped[Vacancy] = relationship(back_populates="search_results")
