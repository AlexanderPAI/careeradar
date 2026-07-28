"""
Resume Advisor Agent
====================

Граф:
  generate_recommendations -> END

Базовый навык анализирует уже созданный профиль и исходный текст резюме,
после чего возвращает приоритетные рекомендации по улучшению резюме.
Новые специализированные навыки добавляются как отдельные промпты в SKILL_PROMPTS.
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Annotated, List, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from backend.llm_providers.base import LLMAdapter
from backend.llm_providers.factory import create_llm_adapter
from backend.utils.prompt_loader import load_prompt

logger = logging.getLogger("RESUME_ADVISOR")

PROMPTS_PATH = Path(__file__).parent / "prompts/base.yaml"
SKILL_PROMPTS = {
    "base": load_prompt(PROMPTS_PATH, "base_recommendations_system"),
    "vacancy_match": load_prompt(PROMPTS_PATH, "vacancy_match_system"),
}


class State(TypedDict):
    messages: Annotated[List, add_messages]
    user_profile: dict
    cv_text: str
    vacancy: dict
    skill: str
    final_answer: str
    operation_id: str


class ResumeAdvisorAgent:
    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self.llm = llm if llm is not None else create_llm_adapter()
        self.graph = self._build_graph()

    async def generate_recommendations(self, state: State) -> dict:
        started_at = time.monotonic()
        skill = state["skill"]
        system_prompt = SKILL_PROMPTS.get(skill)
        if system_prompt is None:
            raise ValueError(f"Unsupported resume advisor skill: {skill}")

        profile_json = json.dumps(state["user_profile"], ensure_ascii=False, indent=2)
        cv_text = state["cv_text"].strip() or (
            "Исходный текст резюме недоступен. Анализируй только профиль."
        )
        vacancy_json = json.dumps(
            state.get("vacancy") or {}, ensure_ascii=False, indent=2
        )
        prompt = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Структурированный профиль:\n{profile_json}\n\n"
                    f"Исходный текст резюме:\n{cv_text}\n\n"
                    f"Данные вакансии:\n{vacancy_json}"
                ),
            },
        ]

        response = await self.llm.chat(prompt)
        final_answer = (
            ((response.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()
        logger.info(
            "operation_id=%s operation=resume_advice skill=%s status=completed "
            "result_chars=%d duration_ms=%d",
            state["operation_id"],
            skill,
            len(final_answer),
            (time.monotonic() - started_at) * 1000,
        )

        return {
            "final_answer": final_answer,
            "messages": [AIMessage(content=final_answer)],
        }

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(State)
        workflow.add_node("generate_recommendations", self.generate_recommendations)
        workflow.set_entry_point("generate_recommendations")
        workflow.add_edge("generate_recommendations", END)
        return workflow.compile()

    async def run(
        self,
        user_profile: dict,
        cv_text: str | None = None,
        *,
        skill: str = "base",
        vacancy: dict | None = None,
    ) -> tuple[str, State]:
        operation_id = uuid.uuid4().hex
        initial_state: State = {
            "messages": [],
            "user_profile": user_profile,
            "cv_text": cv_text or "",
            "vacancy": vacancy or {},
            "skill": skill,
            "final_answer": "",
            "operation_id": operation_id,
        }
        logger.info(
            "operation_id=%s operation=resume_advice skill=%s status=started",
            operation_id,
            skill,
        )
        try:
            result_state = await self.graph.ainvoke(initial_state)
        except Exception:
            logger.error(
                "operation_id=%s operation=resume_advice skill=%s status=failed",
                operation_id,
                skill,
            )
            raise
        return result_state.get("final_answer", ""), result_state
