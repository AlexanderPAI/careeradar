import asyncio
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from frontend.api import get_vacancy_analysis
from frontend.auth import render_account_sidebar, require_auth
from frontend.ui import inject_theme, render_brand, template
from shared.vacancy_urls import safe_vacancy_url

MOSCOW = ZoneInfo("Europe/Moscow")

st.set_page_config(
    page_title="Результат анализа — КарьеРадар",
    page_icon="🟣",
    layout="wide",
)
require_auth()
inject_theme()


def render_vacancy_description(value: str | None) -> str:
    lines = [line.strip() for line in (value or "").splitlines()]
    blocks: list[str] = []
    list_items: list[str] = []

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{item}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    for line in lines:
        if not line:
            flush_list()
            continue
        escaped = html.escape(line.lstrip("•-–—").strip())
        if line.startswith(("•", "-", "–", "—")):
            list_items.append(escaped)
        else:
            flush_list()
            blocks.append(f"<p>{escaped}</p>")
    flush_list()
    return '<div class="vacancy-description-readable">' + "".join(blocks) + "</div>"


with st.sidebar:
    render_brand()
    render_account_sidebar()
    st.page_link("app.py", label="Новый радар")
    st.page_link("pages/profiles.py", label="Карьерные профили")
    st.page_link("pages/vacancy_analyses.py", label="Анализы вакансий")

if st.button("← История анализов"):
    st.switch_page("pages/vacancy_analyses.py")

analysis_id = st.session_state.get("selected_analysis_id")
if not analysis_id:
    st.info("Сначала выберите запись в истории анализов.")
    st.page_link("pages/vacancy_analyses.py", label="Открыть историю")
    st.stop()

try:
    analysis = asyncio.run(get_vacancy_analysis(analysis_id))
except Exception as error:
    st.error(f"Не удалось получить результат анализа: {error}")
    st.stop()

if analysis is None:
    st.error("Анализ не найден.")
    st.stop()

vacancy = analysis["vacancy"]
created_at: datetime = analysis["created_at"]
date_label = created_at.astimezone(MOSCOW).strftime("%d.%m.%Y в %H:%M")

st.markdown(
    f"""
    <div class="analysis-hero">
        <div>
            <div class="kr-eyebrow">Сопоставление профиля и вакансии</div>
            <h1 class="analysis-title">{html.escape(vacancy.get("title") or "—")}</h1>
            <div class="kr-lead">
                {html.escape(vacancy.get("company") or "—")} ·
                профиль {html.escape(analysis.get("profile_name") or "—")}
            </div>
        </div>
        <div class="analysis-source">{html.escape((vacancy.get("source") or "—").upper())}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

cards = template(
    "text_card.html",
    title="Проверено",
    text=html.escape(date_label),
) + template(
    "text_card.html",
    title="Условия",
    text=html.escape(
        " · ".join(
            str(value)
            for value in (
                vacancy.get("salary"),
                vacancy.get("city"),
                vacancy.get("schedule"),
                vacancy.get("experience"),
            )
            if value and value != "—"
        )
        or "Не указаны"
    ),
)
st.markdown(template("cards_row.html", cards=cards), unsafe_allow_html=True)

left, right = st.columns([2.2, 1], gap="large")
with left:
    st.markdown("### Заключение")
    with st.container(border=True):
        st.markdown(analysis["result"])
with right:
    st.markdown("### Вакансия")
    with st.container(border=True):
        skills = vacancy.get("skills") or []
        if skills:
            st.caption("Ключевые навыки")
            st.write(", ".join(skills))
        display_url = safe_vacancy_url(vacancy.get("link"))
        if display_url:
            st.link_button(
                "Открыть оригинал ↗",
                display_url,
                use_container_width=True,
                type="primary",
            )
        else:
            st.caption("Ссылка на оригинал недоступна")

with st.expander("Полное описание вакансии"):
    st.markdown(
        render_vacancy_description(
            vacancy.get("description") or "Описание недоступно."
        ),
        unsafe_allow_html=True,
    )
