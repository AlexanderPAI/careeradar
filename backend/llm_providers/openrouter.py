import asyncio
import logging
import time
import uuid
from typing import Any

import aiohttp

from backend.config import cfg
from backend.llm_providers.base import LLMProviderError

logger = logging.getLogger("OPENROUTER")


class OpenRouterAdapter:
    def __init__(
        self,
        openrouter_url: str,
        openrouter_key: str,
        model: str,
    ):
        self.openrouter_url = openrouter_url
        self.openrouter_key = openrouter_key
        self.model = model

    async def chat(self, prompt: list[dict[str, str]]) -> dict[str, Any]:
        """Send prompt to LLM"""
        operation_id = uuid.uuid4().hex
        started_at = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=240)
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        url=self.openrouter_url,
                        headers={"Authorization": f"Bearer {self.openrouter_key}"},
                        json={"model": self.model, "messages": prompt},
                    ) as response:
                        payload = await response.json(content_type=None)
                        if response.status >= 400:
                            error = LLMProviderError(
                                f"OpenRouter вернул HTTP {response.status} "
                                f"(operation_id={operation_id})"
                            )
                            # Authentication, balance and request errors do not benefit
                            # from an immediate retry with identical parameters.
                            if 400 <= response.status < 500:
                                logger.error(
                                    "operation_id=%s provider=openrouter status=failed "
                                    "http_status=%d attempt=%d",
                                    operation_id,
                                    response.status,
                                    attempt + 1,
                                )
                                raise error from None
                            raise error
                        choices = payload.get("choices") or []
                        choice = choices[0] if choices else {}
                        content = (choice.get("message") or {}).get("content")
                        if not isinstance(content, str) or not content.strip():
                            finish_reason = choice.get("finish_reason") or "не указан"
                            raise LLMProviderError(
                                "OpenRouter вернул пустой ответ "
                                f"(finish_reason={finish_reason})"
                            )
                        logger.info(
                            "operation_id=%s provider=openrouter status=completed "
                            "attempt=%d duration_ms=%d",
                            operation_id,
                            attempt + 1,
                            (time.monotonic() - started_at) * 1000,
                        )
                        return payload
            except (
                TimeoutError,
                aiohttp.ClientConnectionError,
                LLMProviderError,
            ) as exc:
                last_error = exc
                if isinstance(exc, LLMProviderError) and "HTTP 4" in str(exc):
                    break
                if attempt == 0:
                    await asyncio.sleep(1)

        logger.error(
            "operation_id=%s provider=openrouter status=failed attempts=%d "
            "duration_ms=%d error_type=%s",
            operation_id,
            attempt + 1,
            (time.monotonic() - started_at) * 1000,
            type(last_error).__name__ if last_error else "unknown",
        )
        raise LLMProviderError(
            "OpenRouter не дал корректный ответ после двух попыток "
            f"(operation_id={operation_id})"
        ) from last_error


llm = OpenRouterAdapter(
    openrouter_url="https://openrouter.ai/api/v1/chat/completions",
    openrouter_key=cfg.openrouter_key,
    model="z-ai/glm-5.2",
)


async def main() -> None:
    prompt = [{"role": "user", "content": "Расскажи, что ты умеешь?"}]
    await llm.chat(prompt=prompt)


if __name__ == "__main__":
    asyncio.run(main())
