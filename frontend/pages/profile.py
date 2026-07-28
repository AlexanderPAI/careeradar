import asyncio
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
import streamlit as st

from frontend.api import (
    delete_profile,
    get_profile,
    get_resume_recommendations,
    get_search_vacancies,
    repeat_search,
)
from frontend.auth import render_account_sidebar, require_auth
from frontend.ui import inject_theme, render_brand, template
from frontend.vacancies import render_vacancies

MOSCOW = ZoneInfo("Europe/Moscow")

PROFILE_LABELS = {
    "name": "Имя",
    "target_positions": "Позиции",
    "skills": "Навыки",
    "experience_years": "Опыт (лет)",
    "experience_level": "Уровень",
    "salary_expectation": "Ожидаемая ЗП",
    "preferred_schedule": "График",
    "preferred_employment": "Занятость",
    "location": "Город",
    "industries": "Отрасли",
    "languages": "Языки",
    "education": "Образование",
}

st.set_page_config(page_title="Профиль — КарьеРадар", page_icon="🟣", layout="wide")
require_auth()
inject_theme()

with st.sidebar:
    render_brand()
    render_account_sidebar()
    st.page_link("app.py", label="Новый радар")
    st.page_link("pages/profiles.py", label="Карьерные профили")
    st.page_link("pages/vacancy_analyses.py", label="Анализы вакансий")


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(MOSCOW).strftime("%d.%m.%Y в %H:%M")


def render_profile_card(profile: dict) -> str:
    rows = []
    for key, label in PROFILE_LABELS.items():
        value = profile.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            rendered = "".join(
                template("tag.html", value=html.escape(str(item))) for item in value
            )
        else:
            rendered = html.escape(str(value))
        rows.append(template("profile_row.html", label=label, value=rendered))
    return template("profile_card.html", rows="".join(rows))


def render_text_card(title: str, text: str) -> str:
    return template(
        "text_card.html", title=html.escape(title), text=html.escape(text or "—")
    )


def fallback_search_prompt(profile: dict) -> str:
    parts = []
    positions = profile.get("target_positions") or []
    skills = profile.get("skills") or []
    if positions:
        parts.append(f"Ищу вакансии на позиции: {', '.join(positions)}")
    if skills:
        parts.append(f"Ключевые навыки: {', '.join(skills)}")
    if profile.get("experience_level"):
        parts.append(f"Уровень: {profile['experience_level']}")
    if profile.get("location"):
        parts.append(f"Город: {profile['location']}")
    if profile.get("preferred_schedule"):
        parts.append(f"График: {profile['preferred_schedule']}")
    return ". ".join(parts)


if st.button("← Карьерные профили"):
    st.switch_page("pages/profiles.py")

profile_id = st.session_state.get("selected_profile_id")
if not profile_id:
    st.info("Сначала выберите профиль в списке.")
    st.page_link("pages/profiles.py", label="Открыть профили")
    st.stop()

try:
    profile, latest_search, latest_recommendation = asyncio.run(get_profile(profile_id))
except Exception as error:
    st.error(f"Не удалось получить профиль из базы данных: {error}")
    st.stop()

if profile is None:
    st.error("Профиль не найден.")
    st.stop()

last_search_at = (
    format_datetime(latest_search.get("created_at"))
    if latest_search
    else "Подборов ещё не было"
)
st.markdown(
    template(
        "profile_header.html",
        name=html.escape(profile.get("name") or "Без имени"),
        last_search_at=last_search_at,
    ),
    unsafe_allow_html=True,
)

search_prompt = (
    latest_search.get("prompt")
    if latest_search
    else profile.get("search_prompt") or fallback_search_prompt(profile)
)
cards = (
    render_profile_card(profile)
    + render_text_card("Краткое описание", profile.get("summary") or "—")
    + render_text_card(
        "Запрос для поиска вакансий", search_prompt or "Поиск ещё не выполнялся"
    )
)
st.markdown(template("cards_row.html", cards=cards), unsafe_allow_html=True)

if profile.get("resume_expires_at"):
    st.caption(
        "Исходный файл и извлечённый текст резюме будут автоматически удалены "
        f"{format_datetime(profile['resume_expires_at'])}."
    )
else:
    st.caption("Исходный файл и извлечённый текст резюме уже удалены.")

recommendations_key = f"resume_recommendations_{profile_id}"
if latest_recommendation is not None:
    st.session_state[recommendations_key] = latest_recommendation["content"]

if st.button("Получить рекомендации по резюме", use_container_width=True):
    with st.spinner("Анализируем резюме…"):
        try:
            st.session_state[recommendations_key] = asyncio.run(
                get_resume_recommendations(profile_id)
            )
        except aiohttp.ClientConnectorError:
            st.error("Не удалось подключиться к backend.")
        except (TimeoutError, RuntimeError) as error:
            st.error(str(error))

if recommendations := st.session_state.get(recommendations_key):
    with st.expander("Рекомендации по резюме", expanded=True):
        st.markdown(recommendations)

repeat_disabled = not search_prompt
button_label = "Обновить радар" if latest_search else "Сканировать рынок"
if st.button(
    button_label, type="primary", use_container_width=True, disabled=repeat_disabled
):
    with st.status("Сканирование рынка", expanded=True) as status:
        try:
            st.write("Ищем новые возможности на hh.ru и Хабр Карьере…")
            asyncio.run(repeat_search(search_prompt, profile_id))
            status.update(label="Радар обновлён", state="complete")
            st.rerun()
        except aiohttp.ClientConnectorError:
            status.update(label="Backend недоступен", state="error")
            st.error("Не удалось подключиться к backend.")
        except (TimeoutError, RuntimeError) as error:
            status.update(label="Не удалось выполнить подбор", state="error")
            st.error(str(error))

if repeat_disabled:
    st.caption("Недостаточно данных профиля для формирования поискового запроса.")

with st.expander("Удаление профиля"):
    st.warning(
        "Профиль, исходное резюме, подборы, рекомендации и анализы будут удалены "
        "без возможности восстановления."
    )
    confirm_delete = st.checkbox(
        "Я понимаю, что данные будут удалены",
        key=f"confirm_delete_{profile_id}",
    )
    if st.button(
        "Удалить профиль и все данные",
        disabled=not confirm_delete,
        use_container_width=True,
    ):
        try:
            asyncio.run(delete_profile(profile_id))
            st.session_state.pop("selected_profile_id", None)
            st.session_state.pop(recommendations_key, None)
            st.switch_page("pages/profiles.py")
        except (aiohttp.ClientConnectorError, RuntimeError) as error:
            st.error(f"Не удалось удалить профиль: {error}")

if latest_search:
    try:
        vacancies = asyncio.run(
            get_search_vacancies(
                str(latest_search["id"]),
                relevant_only=latest_search.get("filtered_at") is not None,
            )
        )
    except Exception as error:
        st.error(f"Не удалось получить вакансии из базы данных: {error}")
        st.stop()

    render_vacancies(
        vacancies,
        profile_id=str(profile_id),
        csv_filename=f"vacancies_{profile_id}.csv",
    )
