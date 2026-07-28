"""
HH.ru CV Analyzer Agent
=======================

Граф:
  extract_cv  →  build_profile  →  generate_searcher_prompt  →  run_searcher  →  done

Флоу:
  1. extract_cv               — читает файл резюме в текст
  2. build_profile            — LLM строит структурированный профиль пользователя
  3. generate_searcher_prompt — LLM генерирует входной промпт для agent-searcher
  4. run_searcher             — передаёт промпт в Agent-searcher (parse_user_input → run_parser → done)
  5. done                     — возвращает итоговый ответ пользователю
"""

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, List, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from backend.agents.cv_analyzer.tools import extract_cv_text
from backend.llm_providers.base import LLMAdapter
from backend.llm_providers.factory import create_llm_adapter
from backend.privacy import anonymize_text, minimal_profile
from backend.utils.prompt_loader import load_prompt

logger = logging.getLogger("CV_ANALYZER")

# Prompts
build_profile_system = load_prompt(
    Path(__file__).parent / "prompts/base.yaml", "build_profile_system"
)
generate_searcher_prompt_system = load_prompt(
    Path(__file__).parent / "prompts/base.yaml", "generate_searcher_prompt_system"
)


# State
class State(TypedDict):
    messages: Annotated[List, add_messages]
    cv_path: str
    cv_text: str
    llm_cv_text: str
    user_profile: dict
    final_answer: str
    operation_id: str


class CVAnalyzerAgent:
    def __init__(self, llm: LLMAdapter | None = None):
        self.llm = llm if llm is not None else create_llm_adapter()
        self.graph = self._build_graph()

    # Нода 1: читаем файл резюме
    async def extract_cv(self, state: State) -> dict:
        started_at = time.monotonic()
        cv_text = extract_cv_text.invoke({"cv_path": state["cv_path"]})
        llm_cv_text = anonymize_text(cv_text)
        logger.info(
            "operation_id=%s stage=extract_cv status=completed chars=%d duration_ms=%d",
            state["operation_id"],
            len(cv_text),
            (time.monotonic() - started_at) * 1000,
        )

        return {
            "cv_text": cv_text,
            "llm_cv_text": llm_cv_text,
            "messages": [
                AIMessage(content=f"Резюме прочитано ({len(cv_text)} символов).")
            ],
        }

    # Нода 2: создаем профиль пользователя
    async def build_profile(self, state: State) -> dict:
        started_at = time.monotonic()
        prompt = [
            {"role": "system", "content": build_profile_system},
            {"role": "user", "content": state["llm_cv_text"]},
        ]

        response = await self.llm.chat(prompt)
        raw_content = (
            ((response.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()

        try:
            json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
            user_profile = json.loads(json_match.group()) if json_match else {}
        except (json.JSONDecodeError, AttributeError):
            user_profile = {}

        logger.info(
            "operation_id=%s stage=build_profile status=completed fields=%d "
            "duration_ms=%d",
            state["operation_id"],
            len(user_profile),
            (time.monotonic() - started_at) * 1000,
        )

        return {
            "user_profile": user_profile,
            "messages": [AIMessage(content="Профиль кандидата составлен.")],
        }

    # Нода 3: генерируем промпт для agent-searcher
    async def generate_searcher_prompt(self, state: State) -> dict:
        started_at = time.monotonic()
        profile_json = json.dumps(
            minimal_profile(state["user_profile"], purpose="search"),
            ensure_ascii=False,
            indent=2,
        )

        prompt = [
            {"role": "system", "content": generate_searcher_prompt_system},
            {"role": "user", "content": profile_json},
        ]

        response = await self.llm.chat(prompt)
        final_answer = (
            ((response.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()

        logger.info(
            "operation_id=%s stage=generate_search_prompt status=completed "
            "chars=%d duration_ms=%d",
            state["operation_id"],
            len(final_answer),
            (time.monotonic() - started_at) * 1000,
        )

        return {
            "final_answer": final_answer,
            "messages": [AIMessage(content=final_answer)],
        }

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(State)

        workflow.add_node("extract_cv", self.extract_cv)
        workflow.add_node("build_profile", self.build_profile)
        workflow.add_node("generate_searcher_prompt", self.generate_searcher_prompt)

        workflow.set_entry_point("extract_cv")
        workflow.add_edge("extract_cv", "build_profile")
        workflow.add_edge("build_profile", "generate_searcher_prompt")
        workflow.add_edge("generate_searcher_prompt", END)

        return workflow.compile()

    async def run(self, cv_path: str) -> tuple[str, dict[str, Any], State]:
        """
        Args:
            cv_path: путь к файлу резюме (.txt, .pdf, .docx)

        Returns:
            (searcher_prompt, итоговый state)
        """
        operation_id = uuid.uuid4().hex
        started_at = time.monotonic()
        logger.info(
            "operation_id=%s operation=cv_analysis status=started", operation_id
        )
        initial_state: State = {
            "messages": [],
            "cv_path": cv_path,
            "cv_text": "",
            "llm_cv_text": "",
            "user_profile": {},
            "searcher_prompt": "",
            "operation_id": operation_id,
        }

        try:
            result_state = await self.graph.ainvoke(initial_state)
        except Exception:
            logger.error(
                "operation_id=%s operation=cv_analysis status=failed", operation_id
            )
            raise
        logger.info(
            "operation_id=%s operation=cv_analysis status=completed duration_ms=%d",
            operation_id,
            (time.monotonic() - started_at) * 1000,
        )
        return (
            result_state.get("final_answer", ""),
            result_state.get("user_profile", ""),
            result_state,
        )


async def _main():
    cv_agent = CVAnalyzerAgent()
    final_answer, _ = await cv_agent.run("resume.doc")
    with open("final_answer.txt", "w") as f:
        f.write(final_answer)


if __name__ == "__main__":
    asyncio.run(_main())
