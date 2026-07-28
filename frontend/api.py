import os
from datetime import datetime

import aiohttp
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8080")


def auth_headers() -> dict[str, str]:
    token = st.session_state.get("access_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def login(username: str, password: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BACKEND_URL}/v1/auth/token",
            data={"username": username, "password": password},
        ) as response:
            if response.status != 200:
                raise RuntimeError("Неверный логин или пароль")
            return await response.json()


async def _get(path: str, **params):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BACKEND_URL}{path}", headers=auth_headers(), params=params
        ) as response:
            if response.status == 401:
                raise PermissionError("Сессия истекла")
            if response.status == 404:
                return None
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка сервера {response.status}: {await response.text()}"
                )
            return await response.json()


def _dates(item: dict | None) -> dict | None:
    if item is None:
        return None
    for key in (
        "created_at",
        "updated_at",
        "last_search_at",
        "filtered_at",
        "resume_expires_at",
    ):
        if item.get(key) and isinstance(item[key], str):
            item[key] = datetime.fromisoformat(item[key])
    return item


async def get_profiles() -> list[dict]:
    return [_dates(item) for item in (await _get("/v1/history/profiles") or [])]


async def get_profile(
    profile_id: str,
) -> tuple[dict | None, dict | None, dict | None]:
    data = await _get(f"/v1/history/profiles/{profile_id}")
    if data is None:
        return None, None, None
    return (
        _dates(data["profile"]),
        _dates(data["latest_search"]),
        _dates(data["latest_recommendation"]),
    )


async def delete_profile(profile_id: str) -> None:
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        async with session.delete(
            f"{BACKEND_URL}/v1/history/profiles/{profile_id}"
        ) as response:
            if response.status == 404:
                raise RuntimeError("Профиль не найден")
            if response.status != 204:
                raise RuntimeError(
                    f"Ошибка удаления {response.status}: {await response.text()}"
                )


async def get_search_vacancies(search_id: str, *, relevant_only: bool) -> list[dict]:
    return (
        await _get(
            f"/v1/history/searches/{search_id}/vacancies",
            relevant_only=str(relevant_only).lower(),
        )
        or []
    )


async def get_resume_recommendations(profile_id: str) -> str:
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(
        timeout=timeout, headers=auth_headers()
    ) as session:
        async with session.post(
            f"{BACKEND_URL}/v1/resume_advisor/recommendations",
            json={"profile_id": profile_id},
        ) as response:
            if response.status == 404:
                raise RuntimeError("Профиль не найден")
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка анализа {response.status}: {await response.text()}"
                )
            return (await response.json())["recommendations"]


async def analyze_vacancy(profile_id: str, vacancy_id: str) -> str:
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(
        timeout=timeout, headers=auth_headers()
    ) as session:
        async with session.post(
            f"{BACKEND_URL}/v1/vacancy_match/analyze",
            json={"profile_id": profile_id, "vacancy_id": vacancy_id},
        ) as response:
            if response.status == 503:
                data = await response.json()
                raise RuntimeError(
                    data.get("detail") or "Сайт с вакансией временно недоступен."
                )
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка анализа {response.status}: {await response.text()}"
                )
            return (await response.json())["analysis_id"]


async def get_vacancy_analyses() -> list[dict]:
    return [_dates(item) for item in (await _get("/v1/history/vacancy-analyses") or [])]


async def get_vacancy_analysis(analysis_id: str) -> dict | None:
    return _dates(await _get(f"/v1/history/vacancy-analyses/{analysis_id}"))


async def repeat_search(search_prompt: str, profile_id: str) -> list[dict]:
    timeout = aiohttp.ClientTimeout(total=1200)
    async with aiohttp.ClientSession(
        timeout=timeout, headers=auth_headers()
    ) as session:
        async with session.post(
            f"{BACKEND_URL}/v1/searcher/chat",
            json={"message": search_prompt, "profile_id": profile_id},
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка поиска {response.status}: {await response.text()}"
                )
            search_id = (await response.json())["search_id"]
        async with session.post(
            f"{BACKEND_URL}/v1/filter/check", json={"search_id": search_id}
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка фильтрации {response.status}: {await response.text()}"
                )
            return (await response.json())["vacancies"]
