"""
HH.ru Vacancy Filter Agent
===========================

Граф:
  load_data  ->  filter_vacancies  ->  save_result  ->  END

Флоу:
  1. load_data        -- читает выдачу из PostgreSQL и профиль пользователя
  2. filter_vacancies -- LLM анализирует вакансии батчами
                         и решает, релевантна ли каждая профилю
  3. save_result      -- сохраняет решение фильтра в PostgreSQL

Агент фильтрует вакансии на основе профиля кандидата и доступного
контекста вакансии: title, company, query, experience, schedule.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Annotated, List, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from backend.db.connector import async_session
from backend.db.repositories import get_search_rows, mark_relevant
from backend.llm_providers.base import LLMAdapter
from backend.llm_providers.factory import create_llm_adapter
from backend.privacy import minimal_profile
from backend.utils.prompt_loader import load_prompt

logger = logging.getLogger("VACANCY_FILTER")

filter_system_prompt = load_prompt(
    Path(__file__).parent / "prompts/base.yaml", "filter_system"
)

# Сколько вакансий отправляем LLM за один запрос.
BATCH_SIZE = 30


def _format_vacancy_for_prompt(row: dict) -> str:
    """Возвращает компактное описание вакансии для LLM-фильтра."""
    fields = [
        ("Название", row.get("title", "")),
        ("Компания", row.get("company", "")),
        ("Найдено по запросу", row.get("query", "")),
        ("Опыт", row.get("experience", "")),
        ("График", row.get("schedule", "")),
    ]
    return "; ".join(f"{label}: {value}" for label, value in fields if value)


# ---- State ------------------------------------------------------------------


class State(TypedDict):
    messages: Annotated[List, add_messages]
    search_id: str
    user_profile: dict
    all_rows: list[dict]
    filtered_rows: list[dict]
    result_rows: list[dict]


# ---- Agent ------------------------------------------------------------------


class VacancyFilterAgent:
    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm if llm is not None else create_llm_adapter()
        self.graph = self._build_graph()

    # Нода 1: загружаем выдачу из PostgreSQL
    async def load_data(self, state: State) -> dict:
        async with async_session() as session:
            _, all_rows = await get_search_rows(session, state["search_id"])
        logger.info(f"Загружено {len(all_rows)} вакансий поиска {state['search_id']}")

        return {
            "all_rows": all_rows,
            "messages": [AIMessage(content=f"Загружено {len(all_rows)} вакансий.")],
        }

    # Нода 2: фильтруем батчами
    async def filter_vacancies(self, state: State) -> dict:
        all_rows = state["all_rows"]
        profile = minimal_profile(state["user_profile"], purpose="search")
        profile_json = json.dumps(profile, ensure_ascii=False)

        logger.info(f"Вакансий для фильтрации: {len(all_rows)}, батч: {BATCH_SIZE}")

        relevant_row_indices: set[int] = set()

        for batch_start in range(0, len(all_rows), BATCH_SIZE):
            # fmt: off
            batch = all_rows[batch_start: batch_start + BATCH_SIZE]
            numbered = "\n".join(
                f"{idx + 1}. {_format_vacancy_for_prompt(row)}"
                for idx, row in enumerate(batch)
            )
            # fmt: on

            prompt = [
                {"role": "system", "content": filter_system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Профиль кандидата:\n{profile_json}\n\n"
                        f"Список вакансий:\n{numbered}"
                    ),
                },
            ]

            response = await self.llm.chat(prompt)

            raw_content = (
                (response.get("choices") or [{}])[0].get("message") or {}
            ).get("content") or ""

            try:
                match = re.search(r"\[.*?\]", raw_content, re.DOTALL)
                relevant_indices = json.loads(match.group()) if match else []
            except (json.JSONDecodeError, AttributeError):
                relevant_indices = []

            for idx in relevant_indices:
                if isinstance(idx, int) and 1 <= idx <= len(batch):
                    relevant_row_indices.add(batch_start + idx - 1)

            logger.info(
                f"Батч {batch_start // BATCH_SIZE + 1}: "
                f"{len(batch)} -> {len(relevant_indices)} релевантных"
            )

        filtered_rows = [
            row for idx, row in enumerate(all_rows) if idx in relevant_row_indices
        ]
        logger.info(f"Итого: {len(filtered_rows)} / {len(all_rows)}")

        return {
            "filtered_rows": filtered_rows,
            "messages": [
                AIMessage(
                    content=(
                        f"Фильтрация завершена: "
                        f"{len(filtered_rows)} из {len(all_rows)} вакансий релевантны."
                    )
                )
            ],
        }

    # Нода 3: сохраняем решение фильтра в PostgreSQL
    async def save_result(self, state: State) -> dict:
        relevant_links = {row["link"] for row in state["filtered_rows"]}
        async with async_session() as session:
            search, rows = await get_search_rows(session, state["search_id"])
            positions = {
                index for index, row in enumerate(rows) if row["link"] in relevant_links
            }
            await mark_relevant(session, search, positions)

        return {
            "result_rows": state["filtered_rows"],
            "messages": [AIMessage(content="Результат фильтрации сохранён.")],
        }

    # Сборка графа
    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(State)

        workflow.add_node("load_data", self.load_data)
        workflow.add_node("filter_vacancies", self.filter_vacancies)
        workflow.add_node("save_result", self.save_result)

        workflow.set_entry_point("load_data")
        workflow.add_edge("load_data", "filter_vacancies")
        workflow.add_edge("filter_vacancies", "save_result")
        workflow.add_edge("save_result", END)

        return workflow.compile()

    async def run(self, search_id: str, user_profile: dict) -> tuple[list[dict], State]:
        """
        Args:
            search_id   : идентификатор поиска в PostgreSQL
            user_profile: профиль кандидата от cv_analyzer-а

        Returns:
            (отфильтрованные вакансии, итоговый state)
        """
        initial_state: State = {
            "messages": [],
            "search_id": search_id,
            "user_profile": user_profile,
            "all_rows": [],
            "filtered_rows": [],
            "result_rows": [],
        }

        result_state = await self.graph.ainvoke(initial_state)
        return result_state.get("result_rows", []), result_state


# ---- CLI --------------------------------------------------------------------


async def _main():
    import sys

    if len(sys.argv) < 3:
        print(
            "Использование: python vacancy_filter_agent.py <search_id> <profile.json>"
        )
        return

    with open(sys.argv[2], encoding="utf-8") as profile_file:
        user_profile = json.load(profile_file)

    agent = VacancyFilterAgent()
    rows, _ = await agent.run(sys.argv[1], user_profile)
    print(f"\nПодходящих вакансий: {len(rows)}")


if __name__ == "__main__":
    asyncio.run(_main())
