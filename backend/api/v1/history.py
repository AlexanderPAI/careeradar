import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.connector import get_session
from backend.db.models import (
    CandidateProfile,
    ResumeRecommendation,
    SearchResult,
    SearchRun,
    User,
    VacancyAnalysis,
)
from backend.resume_storage import delete_resume_file
from backend.security import get_current_user
from shared.vacancy_urls import safe_vacancy_url

router = APIRouter(prefix="/v1/history", tags=["history"])


def _profile_data(profile: CandidateProfile) -> dict:
    fields = (
        "id",
        "name",
        "target_positions",
        "skills",
        "experience_years",
        "experience_level",
        "salary_expectation",
        "preferred_schedule",
        "preferred_employment",
        "location",
        "industries",
        "languages",
        "education",
        "summary",
        "search_prompt",
        "source_filename",
        "resume_expires_at",
        "created_at",
        "updated_at",
    )
    return {field: getattr(profile, field) for field in fields}


def _search_data(search: SearchRun) -> dict:
    fields = (
        "id",
        "prompt",
        "queries",
        "filters",
        "area",
        "max_pages",
        "status",
        "total_found",
        "relevant_count",
        "created_at",
        "filtered_at",
    )
    return {field: getattr(search, field) for field in fields}


def _recommendation_data(recommendation: ResumeRecommendation) -> dict:
    fields = ("id", "skill", "content", "created_at")
    return {field: getattr(recommendation, field) for field in fields}


@router.get("/profiles")
async def profiles(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.scalars(
            select(CandidateProfile)
            .where(CandidateProfile.user_id == user.id)
            .options(selectinload(CandidateProfile.searches))
            .order_by(CandidateProfile.created_at.desc())
        )
    ).all()
    result = []
    for profile in rows:
        latest = (
            max(profile.searches, key=lambda item: item.created_at)
            if profile.searches
            else None
        )
        item = _profile_data(profile)
        item.update(
            latest_search_id=latest.id if latest else None,
            latest_queries=latest.queries if latest else None,
            last_search_at=latest.created_at if latest else None,
            relevant_count=latest.relevant_count if latest else None,
            total_found=latest.total_found if latest else None,
        )
        result.append(item)
    result.sort(
        key=lambda item: item["last_search_at"] or item["created_at"], reverse=True
    )
    return result


@router.get("/profiles/{profile_id}")
async def profile_detail(
    profile_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.id == profile_id, CandidateProfile.user_id == user.id)
        .options(selectinload(CandidateProfile.searches))
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    latest = (
        max(profile.searches, key=lambda item: item.created_at)
        if profile.searches
        else None
    )
    latest_recommendation = await session.scalar(
        select(ResumeRecommendation)
        .where(ResumeRecommendation.profile_id == profile.id)
        .order_by(
            ResumeRecommendation.created_at.desc(),
            ResumeRecommendation.id.desc(),
        )
        .limit(1)
    )
    return {
        "profile": _profile_data(profile),
        "latest_search": _search_data(latest) if latest else None,
        "latest_recommendation": (
            _recommendation_data(latest_recommendation)
            if latest_recommendation
            else None
        ),
    }


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    profile = await session.scalar(
        select(CandidateProfile).where(
            CandidateProfile.id == profile_id,
            CandidateProfile.user_id == user.id,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    source_path = profile.source_path
    delete_resume_file(source_path)
    await session.delete(profile)
    await session.commit()


@router.get("/searches/{search_id}/vacancies")
async def search_vacancies(
    search_id: uuid.UUID,
    relevant_only: bool = Query(False),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    search = await session.scalar(
        select(SearchRun)
        .where(SearchRun.id == search_id, SearchRun.user_id == user.id)
        .options(selectinload(SearchRun.results).selectinload(SearchResult.vacancy))
    )
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return [
        {
            "vacancy_id": result.vacancy.id,
            "title": result.vacancy.title,
            "company": result.vacancy.company,
            "salary": result.vacancy.salary_text,
            "city": result.vacancy.city,
            "schedule": result.vacancy.schedule,
            "experience": result.vacancy.experience,
            "link": safe_vacancy_url(result.vacancy.external_url),
            "source": result.vacancy.source,
            "query": result.query,
        }
        for result in search.results
        if not relevant_only or result.is_relevant is True
    ]


@router.get("/vacancy-analyses")
async def vacancy_analyses(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.scalars(
            select(VacancyAnalysis)
            .where(VacancyAnalysis.user_id == user.id)
            .order_by(
                VacancyAnalysis.created_at.desc(),
                VacancyAnalysis.id.desc(),
            )
        )
    ).all()
    return [
        {
            "id": row.id,
            "profile_id": row.profile_id,
            "vacancy_id": row.vacancy_id,
            "vacancy_title": row.vacancy_snapshot.get("title") or "—",
            "company": row.vacancy_snapshot.get("company") or "—",
            "source": row.vacancy_snapshot.get("source") or "—",
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/vacancy-analyses/{analysis_id}")
async def vacancy_analysis_detail(
    analysis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    analysis = await session.scalar(
        select(VacancyAnalysis).where(
            VacancyAnalysis.id == analysis_id,
            VacancyAnalysis.user_id == user.id,
        )
    )
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    profile = await session.scalar(
        select(CandidateProfile).where(
            CandidateProfile.id == analysis.profile_id,
            CandidateProfile.user_id == user.id,
        )
    )
    vacancy_snapshot = dict(analysis.vacancy_snapshot)
    vacancy_snapshot["link"] = safe_vacancy_url(vacancy_snapshot.get("link"))
    return {
        "id": analysis.id,
        "profile_id": analysis.profile_id,
        "profile_name": profile.name if profile else "—",
        "vacancy_id": analysis.vacancy_id,
        "vacancy": vacancy_snapshot,
        "result": analysis.result,
        "created_at": analysis.created_at,
    }
