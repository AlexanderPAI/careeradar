import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.v1.auth import router as auth_router
from backend.api.v1.endpoints import router
from backend.api.v1.history import router as history_router
from backend.config import cfg
from backend.db.connector import async_session
from backend.llm_providers.base import LLMProviderError
from backend.resume_storage import ensure_private_storage, purge_expired_resumes

logger = logging.getLogger("RESUME_RETENTION")


async def _resume_cleanup_loop() -> None:
    while True:
        try:
            async with async_session() as session:
                await purge_expired_resumes(session)
        except Exception:
            logger.exception("Не удалось выполнить очистку просроченных резюме")
        await asyncio.sleep(cfg.resume_cleanup_interval_minutes * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_private_storage()
    cleanup_task = asyncio.create_task(_resume_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(router)


@app.exception_handler(LLMProviderError)
async def llm_provider_error_handler(
    request: Request, exc: LLMProviderError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
