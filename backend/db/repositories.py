import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import (
    CandidateProfile,
    ResumeRecommendation,
    SearchResult,
    SearchRun,
    Vacancy,
    VacancyAnalysis,
)
from shared.vacancy_urls import safe_vacancy_url, validate_vacancy_url

logger = logging.getLogger("VACANCY_STORAGE")


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d[\d\s\u202f]*", str(value))
    digits = re.sub(r"\D", "", match.group()) if match else ""
    return int(digits) if digits else None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(match.group().replace(",", ".")) if match else None


def normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Нормализует нестабильные типы из ответа LLM для колонок профиля."""
    return {
        "name": data.get("name"),
        "target_positions": _string_list(data.get("target_positions")),
        "skills": _string_list(data.get("skills")),
        "experience_years": _optional_float(data.get("experience_years")),
        "experience_level": data.get("experience_level"),
        "salary_expectation": _optional_int(data.get("salary_expectation")),
        "preferred_schedule": data.get("preferred_schedule"),
        "preferred_employment": data.get("preferred_employment"),
        "location": data.get("location"),
        "industries": _string_list(data.get("industries")),
        "languages": _string_list(data.get("languages")),
        "education": _string_list(data.get("education")),
        "summary": data.get("summary"),
    }


async def create_profile(
    session: AsyncSession,
    data: dict[str, Any],
    user_id: uuid.UUID,
    *,
    search_prompt: str | None = None,
    source_filename: str | None = None,
    source_path: str | None = None,
    cv_text: str | None = None,
    resume_expires_at: datetime | None = None,
) -> CandidateProfile:
    normalized = normalize_profile(data)
    profile = CandidateProfile(
        **normalized,
        user_id=uuid.UUID(str(user_id)),
        search_prompt=search_prompt,
        source_filename=source_filename,
        source_path=source_path,
        cv_text=cv_text,
        resume_expires_at=resume_expires_at,
        raw_data=data,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def save_resume_recommendation(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID,
    skill: str,
    content: str,
) -> ResumeRecommendation:
    recommendation = ResumeRecommendation(
        profile_id=uuid.UUID(str(profile_id)),
        skill=skill,
        content=content,
    )
    session.add(recommendation)
    await session.commit()
    await session.refresh(recommendation)
    return recommendation


async def save_vacancy_analysis(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    profile_id: uuid.UUID,
    vacancy_id: uuid.UUID,
    result: str,
    vacancy_snapshot: dict[str, Any],
) -> VacancyAnalysis:
    vacancy_snapshot = dict(vacancy_snapshot)
    validated_url = validate_vacancy_url(vacancy_snapshot.get("link"))
    vacancy_snapshot["link"] = validated_url.url
    vacancy_snapshot["source"] = validated_url.source
    analysis = VacancyAnalysis(
        user_id=uuid.UUID(str(user_id)),
        profile_id=uuid.UUID(str(profile_id)),
        vacancy_id=uuid.UUID(str(vacancy_id)),
        skill="vacancy_match",
        result=result,
        vacancy_snapshot=vacancy_snapshot,
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return analysis


async def save_search(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID | None,
    user_id: uuid.UUID,
    prompt: str,
    queries: list[str],
    filters: dict[str, Any],
    area: int,
    max_pages: int,
    rows: list[dict[str, Any]],
) -> SearchRun:
    validated_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            validated_url = validate_vacancy_url(row.get("link"))
        except ValueError:
            logger.warning("Отклонена вакансия с недопустимой ссылкой")
            continue
        validated_row = dict(row)
        validated_row["link"] = validated_url.url
        validated_row["source"] = validated_url.source
        validated_rows.append(validated_row)

    search = SearchRun(
        user_id=user_id,
        profile_id=uuid.UUID(str(profile_id)) if profile_id else None,
        prompt=prompt,
        queries=queries,
        filters=filters,
        area=area,
        max_pages=max_pages,
        total_found=len(validated_rows),
    )
    session.add(search)
    await session.flush()

    for position, row in enumerate(validated_rows):
        link = row["link"]
        vacancy = await session.scalar(
            select(Vacancy).where(Vacancy.external_url == link)
        )
        source = row["source"]
        if vacancy is None:
            vacancy = Vacancy(
                source=source,
                external_url=link,
                title=row.get("title") or "—",
                company=row.get("company"),
                salary_text=row.get("salary"),
                city=row.get("city"),
                schedule=row.get("schedule"),
                experience=row.get("experience"),
                raw_data=row,
            )
            session.add(vacancy)
            await session.flush()
        else:
            vacancy.source = source
            vacancy.title = row.get("title") or vacancy.title
            vacancy.company = row.get("company")
            vacancy.salary_text = row.get("salary")
            vacancy.city = row.get("city")
            vacancy.schedule = row.get("schedule")
            vacancy.experience = row.get("experience")
            vacancy.raw_data = row

        session.add(
            SearchResult(
                search_run=search,
                vacancy=vacancy,
                query=row.get("query"),
                position=position,
            )
        )

    await session.commit()
    await session.refresh(search)
    return search


async def get_search_rows(
    session: AsyncSession, search_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> tuple[SearchRun, list[dict[str, Any]]]:
    search_id = uuid.UUID(str(search_id))
    query = select(SearchRun).where(SearchRun.id == search_id)
    if user_id is not None:
        query = query.where(SearchRun.user_id == user_id)
    search = await session.scalar(
        query.options(
            selectinload(SearchRun.results).selectinload(SearchResult.vacancy)
        )
    )
    if search is None:
        raise LookupError(f"Search {search_id} not found")
    rows = [
        {
            "title": result.vacancy.title,
            "company": result.vacancy.company,
            "salary": result.vacancy.salary_text,
            "city": result.vacancy.city,
            "schedule": result.vacancy.schedule,
            "experience": result.vacancy.experience,
            "link": safe_vacancy_url(result.vacancy.external_url),
            "query": result.query,
            "source": result.vacancy.source,
        }
        for result in search.results
    ]
    return search, rows


async def mark_relevant(
    session: AsyncSession, search: SearchRun, relevant_positions: set[int]
) -> None:
    for result in search.results:
        result.is_relevant = result.position in relevant_positions
    search.relevant_count = len(relevant_positions)
    search.filtered_at = datetime.now(timezone.utc)
    await session.commit()
