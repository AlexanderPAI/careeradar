from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized bodies while they are being received by the backend."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await self._respond(send, 400, "Некорректный Content-Length")
                return
            if declared_size < 0:
                await self._respond(send, 400, "Некорректный Content-Length")
                return
            if declared_size > self.max_bytes:
                await self._respond(send, 413, self._limit_detail())
                return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._respond(send, 413, self._limit_detail())

    def _limit_detail(self) -> str:
        limit_mebibytes = self.max_bytes / (1024 * 1024)
        return f"Размер запроса превышает {limit_mebibytes:g} МБ"

    @staticmethod
    async def _respond(
        send: Callable[[dict[str, Any]], Awaitable[None]],
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response({"type": "http", "method": "POST"}, _empty_receive, send)


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.disconnect"}
