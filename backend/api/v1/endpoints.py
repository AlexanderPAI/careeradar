import uuid

import aiohttp
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from playwright.async_api import Error as PlaywrightError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cv_analyzer.agent import CVAnalyzerAgent
from backend.agents.resume_advisor.agent import ResumeAdvisorAgent
from backend.agents.searcher.agent import Agent as SearchAgent
from backend.agents.vacancy_filter.agent import VacancyFilterAgent
from backend.api.v1.schemes import (
    ResumeRecommendationsRequest,
    SearcherRequest,
    VacancyCheckerRequest,
    VacancyMatchRequest,
)
from backend.db.connector import get_session
from backend.db.models import CandidateProfile, SearchResult, SearchRun, User, Vacancy
from backend.db.repositories import (
    create_profile,
    save_resume_recommendation,
    save_vacancy_analysis,
)
from backend.file_validation import ValidatedResumeFile, validate_resume_file
from backend.llm_providers.base import LLMProviderError
from backend.privacy import anonymize_text, require_llm_consent
from backend.resume_storage import expires_at, save_upload
from backend.security import get_current_user
from backend.utils.parser import CareerHabrParser, HHParser
from shared.vacancy_urls import validate_vacancy_url

router = APIRouter(prefix="/v1", dependencies=[Depends(get_current_user)])

cv_analyzer_agent = CVAnalyzerAgent()
resume_advisor_agent = ResumeAdvisorAgent()
search_agent = SearchAgent()
vacancy_filter_agent = VacancyFilterAgent()
hh_parser = HHParser([], area=1, max_pages=1)
habr_parser = CareerHabrParser([], area=1, max_pages=1)


def _validated_upload(file: UploadFile) -> ValidatedResumeFile:
    try:
        return validate_resume_file(file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload_cv")
async def upload_cv(file: UploadFile = File(...)):
    detected = _validated_upload(file)
    save_filename = f"{uuid.uuid4()}{detected.extension}"
    file_path = save_upload(file, save_filename)

    return {
        "original_filename": file.filename,
        "stored_filename": save_filename,
        "content_type": detected.content_type,
        "path": str(file_path),
    }


@router.post("/cv_analyzer/send_cv")
async def cv_analyzer(
    file: UploadFile = File(...),
    llm_processing_consent: bool = Form(False),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_llm_consent(llm_processing_consent)
    detected = _validated_upload(file)
    save_filename = f"{uuid.uuid4()}{detected.extension}"
    file_path = save_upload(file, save_filename)

    try:
        search_prompt, user_profile, state = await cv_analyzer_agent.run(str(file_path))
        profile = await create_profile(
            session,
            user_profile,
            user_id=user.id,
            search_prompt=search_prompt,
            source_filename=file.filename,
            source_path=str(file_path),
            cv_text=state.get("cv_text"),
            resume_expires_at=expires_at(),
        )
    except LLMProviderError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BaseException:
        file_path.unlink(missing_ok=True)
        raise

    return {
        "search_prompt": search_prompt,
        "user_profile": user_profile,
        "profile_id": str(profile.id),
    }


@router.post("/resume_advisor/recommendations")
async def resume_recommendations(
    request: ResumeRecommendationsRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_llm_consent(request.llm_processing_consent)
    profile = await session.scalar(
        select(CandidateProfile).where(
            CandidateProfile.id == request.profile_id,
            CandidateProfile.user_id == user.id,
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile_id = profile.id
    recommendations, _ = await resume_advisor_agent.run(
        profile.raw_data,
        profile.cv_text,
        skill="base",
    )
    saved_recommendation = await save_resume_recommendation(
        session,
        profile_id=profile_id,
        skill="base",
        content=recommendations,
    )
    return {
        "profile_id": str(profile_id),
        "recommendations": recommendations,
        "recommendation_id": str(saved_recommendation.id),
        "created_at": saved_recommendation.created_at,
    }


@router.post("/vacancy_match/analyze")
async def analyze_vacancy_match(
    request: VacancyMatchRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_llm_consent(request.llm_processing_consent)
    profile = await session.scalar(
        select(CandidateProfile).where(
            CandidateProfile.id == request.profile_id,
            CandidateProfile.user_id == user.id,
        )
    )
    vacancy = await session.scalar(
        select(Vacancy)
        .join(SearchResult, SearchResult.vacancy_id == Vacancy.id)
        .join(SearchRun, SearchRun.id == SearchResult.search_run_id)
        .where(
            Vacancy.id == request.vacancy_id,
            SearchRun.user_id == user.id,
            SearchRun.profile_id == request.profile_id,
        )
        .limit(1)
    )
    if profile is None or vacancy is None:
        raise HTTPException(status_code=404, detail="Profile or vacancy not found")

    profile_id = profile.id
    vacancy_id = vacancy.id
    try:
        validated_url = validate_vacancy_url(vacancy.external_url)
        if validated_url.source == "habr":
            vacancy_data = await habr_parser.parse_vacancy(validated_url.url)
        elif validated_url.source == "hh":
            vacancy_data = await hh_parser.parse_vacancy(validated_url.url)
        else:
            raise ValueError("Неподдерживаемый источник вакансии")
    except (aiohttp.ClientError, PlaywrightError, TimeoutError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Сайт с вакансией временно недоступен, заблокировал загрузку "
                "или вакансия уже закрыта. Попробуйте повторить позже."
            ),
        ) from exc

    result, _ = await resume_advisor_agent.run(
        profile.raw_data,
        profile.cv_text,
        skill="vacancy_match",
        vacancy=vacancy_data,
    )
    analysis = await save_vacancy_analysis(
        session,
        user_id=user.id,
        profile_id=profile_id,
        vacancy_id=vacancy_id,
        result=result,
        vacancy_snapshot=vacancy_data,
    )
    return {
        "analysis_id": str(analysis.id),
        "created_at": analysis.created_at,
    }


@router.post("/searcher/chat")
async def searcher_chat(
    searcher_request: SearcherRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_llm_consent(searcher_request.llm_processing_consent)
    if searcher_request.profile_id is not None:
        profile = await session.scalar(
            select(CandidateProfile).where(
                CandidateProfile.id == searcher_request.profile_id,
                CandidateProfile.user_id == user.id,
            )
        )
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
    search_id = await search_agent.run(
        anonymize_text(searcher_request.message),
        str(searcher_request.profile_id) if searcher_request.profile_id else None,
        str(user.id),
    )
    return {"search_id": search_id}


@router.post("/filter/check")
async def filter_check(
    request: VacancyCheckerRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_llm_consent(request.llm_processing_consent)
    profile = await session.scalar(
        select(CandidateProfile)
        .join(CandidateProfile.searches)
        .where(
            CandidateProfile.user_id == user.id,
            CandidateProfile.searches.any(id=request.search_id, user_id=user.id),
        )
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile for search not found")
    rows, _ = await vacancy_filter_agent.run(str(request.search_id), profile.raw_data)
    return {
        "search_id": str(request.search_id),
        "total_count": len(rows),
        "vacancies": rows,
    }
