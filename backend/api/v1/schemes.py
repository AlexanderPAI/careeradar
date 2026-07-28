import uuid

from pydantic import BaseModel, Field


class SearcherRequest(BaseModel):
    message: str = Field(..., description="Сообщение для AgentSearcher")
    profile_id: uuid.UUID | None = Field(None, description="Идентификатор профиля")
    llm_processing_consent: bool = False


class VacancyCheckerRequest(BaseModel):
    search_id: uuid.UUID = Field(..., description="Идентификатор поиска")
    llm_processing_consent: bool = False


class ResumeRecommendationsRequest(BaseModel):
    profile_id: uuid.UUID = Field(..., description="Идентификатор профиля")
    llm_processing_consent: bool = False


class VacancyMatchRequest(BaseModel):
    profile_id: uuid.UUID = Field(..., description="Идентификатор профиля")
    vacancy_id: uuid.UUID = Field(..., description="Идентификатор вакансии")
    llm_processing_consent: bool = False
