import asyncio

import aiohttp
import pandas as pd
import streamlit as st

from frontend.api import analyze_vacancy


def render_vacancies(
    vacancies: list[dict],
    *,
    profile_id: str,
    csv_filename: str,
    llm_consent: bool,
) -> None:
    dataframe = pd.DataFrame(vacancies)
    with st.expander(f"В зоне интереса — {len(dataframe)} вакансий", expanded=True):
        if dataframe.empty:
            st.info("В последнем подборе нет подходящих вакансий.")
            return

        for index, vacancy in enumerate(vacancies):
            with st.container(border=True):
                details, links, action = st.columns(
                    [4.2, 1.2, 1.7], vertical_alignment="center"
                )
                with details:
                    st.markdown(f"**{vacancy.get('title') or '—'}**")
                    st.caption(
                        " · ".join(
                            str(value)
                            for value in (
                                vacancy.get("company"),
                                vacancy.get("salary"),
                                vacancy.get("city"),
                            )
                            if value and value != "—"
                        )
                    )
                with links:
                    st.link_button(
                        "Вакансия ↗",
                        vacancy["link"],
                        use_container_width=True,
                    )
                with action:
                    if st.button(
                        "Проверить соответствие",
                        key=f"match_{vacancy['vacancy_id']}_{index}",
                        use_container_width=True,
                        type="primary",
                        disabled=not llm_consent,
                    ):
                        with st.spinner("Сопоставляем профиль и вакансию…"):
                            try:
                                analysis_id = asyncio.run(
                                    analyze_vacancy(
                                        profile_id,
                                        str(vacancy["vacancy_id"]),
                                        consent=llm_consent,
                                    )
                                )
                                st.session_state["selected_analysis_id"] = analysis_id
                                st.switch_page("pages/vacancy_analysis.py")
                            except (
                                aiohttp.ClientConnectorError,
                                TimeoutError,
                                RuntimeError,
                            ) as error:
                                st.error(str(error))

        st.download_button(
            "Скачать CSV",
            dataframe.to_csv(index=False).encode("utf-8-sig"),
            file_name=csv_filename,
            mime="text/csv",
        )
