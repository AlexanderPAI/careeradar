import asyncio
import logging
import time
import uuid
from typing import Any

import aiohttp

from backend.llm_providers.base import LLMProviderError

logger = logging.getLogger("GIGACHAT")


class GigaChatAdapter:
    """GigaChat REST API adapter with the same public contract as OpenRouterAdapter."""

    def __init__(
        self,
        gigachat_url: str,
        gigachat_key: str,
        model: str,
        *,
        oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        scope: str = "GIGACHAT_API_PERS",
        verify_ssl_certs: bool = False,
    ):
        self.gigachat_url = gigachat_url
        self.gigachat_key = gigachat_key
        self.model = model
        self.oauth_url = oauth_url
        self.scope = scope
        self.verify_ssl_certs = verify_ssl_certs
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def _get_access_token(
        self, session: aiohttp.ClientSession, *, force_refresh: bool = False
    ) -> str:
        if (
            not force_refresh
            and self._access_token
            and time.time() < self._token_expires_at - 30
        ):
            return self._access_token

        async with self._token_lock:
            if (
                not force_refresh
                and self._access_token
                and time.time() < self._token_expires_at - 30
            ):
                return self._access_token

            async with session.post(
                self.oauth_url,
                ssl=self.verify_ssl_certs,
                headers={
                    "Authorization": f"Basic {self.gigachat_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": self.scope},
            ) as response:
                payload = await response.json(content_type=None)
                if response.status >= 400:
                    raise LLMProviderError(
                        f"GigaChat OAuth вернул HTTP {response.status}: "
                        f"{self._error_message(payload)}"
                    )

            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise LLMProviderError("GigaChat OAuth вернул пустой access token")

            expires_at = payload.get("expires_at", 0)
            try:
                expires_at = float(expires_at)
            except (TypeError, ValueError):
                expires_at = 0.0
            if expires_at > 10_000_000_000:
                expires_at /= 1000

            self._access_token = token
            self._token_expires_at = expires_at or time.time() + 30 * 60
            return token

    @staticmethod
    def _error_message(payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message") or error
        return payload.get("message") or error or payload

    async def chat(self, prompt: list[dict[str, str]]) -> dict[str, Any]:
        """Send prompt to GigaChat and return its OpenAI-compatible response."""
        operation_id = uuid.uuid4().hex
        started_at = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=240)
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    token = await self._get_access_token(session)
                    async with session.post(
                        self.gigachat_url,
                        ssl=self.verify_ssl_certs,
                        headers={"Authorization": f"Bearer {token}"},
                        json={"model": self.model, "messages": prompt},
                    ) as response:
                        payload = await response.json(content_type=None)
                        if response.status == 401 and attempt == 0:
                            self._access_token = None
                            self._token_expires_at = 0.0
                            raise aiohttp.ClientConnectionError(
                                "GigaChat access token был отклонён"
                            )
                        if response.status >= 400:
                            error = LLMProviderError(
                                f"GigaChat вернул HTTP {response.status} "
                                f"(operation_id={operation_id})"
                            )
                            if 400 <= response.status < 500:
                                logger.error(
                                    "operation_id=%s provider=gigachat status=failed "
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
                                "GigaChat вернул пустой ответ "
                                f"(finish_reason={finish_reason})"
                            )
                        logger.info(
                            "operation_id=%s provider=gigachat status=completed "
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
            "operation_id=%s provider=gigachat status=failed attempts=%d "
            "duration_ms=%d error_type=%s",
            operation_id,
            attempt + 1,
            (time.monotonic() - started_at) * 1000,
            type(last_error).__name__ if last_error else "unknown",
        )
        raise LLMProviderError(
            "GigaChat не дал корректный ответ после двух попыток "
            f"(operation_id={operation_id})"
        ) from last_error
