import asyncio
import html

import aiohttp
import streamlit as st

from frontend.api import BACKEND_URL, auth_headers, get_search_vacancies
from frontend.auth import render_account_sidebar, require_auth
from frontend.ui import inject_theme, radar_art, render_brand, template
from frontend.vacancies import render_vacancies

CV_ANALYZER_URL = f"{BACKEND_URL}/v1/cv_analyzer/send_cv"
SEARCHER_URL = f"{BACKEND_URL}/v1/searcher/chat"
FILTER_URL = f"{BACKEND_URL}/v1/filter/check"

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
}

st.set_page_config(page_title="КарьеРадар", page_icon="🟣", layout="wide")
require_auth()


async def call_cv_analyzer(file_bytes, filename, content_type):
    form_data = aiohttp.FormData()
    form_data.add_field(
        "file", file_bytes, filename=filename, content_type=content_type
    )
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        async with session.post(
            CV_ANALYZER_URL, data=form_data, timeout=aiohttp.ClientTimeout(total=1200)
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка сервера {response.status}: {await response.text()}"
                )
            return await response.json()


async def call_searcher(search_prompt: str, profile_id: str) -> str:
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        async with session.post(
            SEARCHER_URL,
            json={"message": search_prompt, "profile_id": profile_id},
            timeout=aiohttp.ClientTimeout(total=1200),
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка сервера {response.status}: {await response.text()}"
                )
            return (await response.json())["search_id"]


async def call_filter(search_id: str) -> list[dict]:
    async with aiohttp.ClientSession(headers=auth_headers()) as session:
        async with session.post(
            FILTER_URL,
            json={"search_id": search_id},
            timeout=aiohttp.ClientTimeout(total=1200),
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Ошибка сервера {response.status}: {await response.text()}"
                )
            return (await response.json())["vacancies"]


def render_profile_card(profile: dict) -> str:
    rows = []
    for key, label in PROFILE_LABELS.items():
        value = profile.get(key)
        if not value:
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


with st.sidebar:
    render_brand()
    render_account_sidebar()
    st.page_link("app.py", label="Новый радар")
    st.page_link("pages/profiles.py", label="Карьерные профили")
    st.page_link("pages/vacancy_analyses.py", label="Анализы вакансий")

inject_theme()
st.markdown(template("home_hero.html", radar=radar_art()), unsafe_allow_html=True)

uploaded_file = st.file_uploader(
    label="Настроить КарьеРадар по резюме",
    type=["pdf", "docx", "doc", "txt"],
    help="Поддерживаются PDF, DOCX, DOC и TXT",
    label_visibility="collapsed",
)

if uploaded_file is not None and st.button(
    "Анализировать резюме", type="primary", use_container_width=True
):
    st.session_state.pop("api_response", None)
    st.session_state.pop("vacancies", None)
    with st.spinner("Настраиваем ваш КарьеРадар…"):
        try:
            st.session_state["api_response"] = asyncio.run(
                call_cv_analyzer(
                    uploaded_file.getvalue(), uploaded_file.name, uploaded_file.type
                )
            )
            st.session_state["vacancies"] = None
        except aiohttp.ClientConnectorError:
            st.error("Не удалось подключиться к backend.")
            st.stop()
        except asyncio.TimeoutError:
            st.error("Сервер не ответил за 20 минут.")
            st.stop()
        except RuntimeError as error:
            st.error(str(error))
            st.stop()

if "api_response" in st.session_state:
    api_response = st.session_state["api_response"]
    profile = api_response.get("user_profile", {})
    search_prompt = api_response.get("search_prompt", "—")
    cards = (
        render_profile_card(profile)
        + render_text_card("Краткое описание", profile.get("summary", "—"))
        + render_text_card("Запрос для поиска вакансий", search_prompt)
    )
    st.markdown(template("cards_row.html", cards=cards), unsafe_allow_html=True)

    if st.button("Сканировать рынок", type="primary", use_container_width=True):
        with st.spinner("КарьеРадар сканирует рынок…"):
            try:
                search_id = asyncio.run(
                    call_searcher(search_prompt, api_response.get("profile_id"))
                )
                asyncio.run(call_filter(search_id))
                st.session_state["vacancies"] = asyncio.run(
                    get_search_vacancies(search_id, relevant_only=True)
                )
            except aiohttp.ClientConnectorError:
                st.error("Не удалось подключиться к backend.")
                st.stop()
            except asyncio.TimeoutError:
                st.error("Сервер не ответил за 20 минут.")
                st.stop()
            except RuntimeError as error:
                st.error(str(error))
                st.stop()

if st.session_state.get("vacancies") is not None:
    render_vacancies(
        st.session_state["vacancies"],
        profile_id=str(st.session_state["api_response"]["profile_id"]),
        csv_filename="vacancies.csv",
    )
