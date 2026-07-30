import multiprocessing
import os
import sys
from pathlib import Path
from typing import Any

from backend.config import cfg


class DocumentProcessingError(ValueError):
    pass


class DocumentProcessingTimeoutError(TimeoutError):
    pass


def _set_resource_limit(resource_module: Any, name: str, value: int) -> None:
    limit = getattr(resource_module, name, None)
    if limit is not None:
        resource_module.setrlimit(limit, (value, value))


def _apply_worker_limits() -> None:
    if sys.platform != "linux":
        return
    import resource

    _set_resource_limit(resource, "RLIMIT_CORE", 0)
    _set_resource_limit(resource, "RLIMIT_CPU", cfg.document_parser_cpu_seconds)
    _set_resource_limit(
        resource,
        "RLIMIT_AS",
        cfg.document_parser_memory_bytes,
    )
    _set_resource_limit(resource, "RLIMIT_NOFILE", 64)


def _worker(path: str, sender: Any) -> None:
    try:
        _apply_worker_limits()
        from backend.utils.readers import FileReader

        os.environ.clear()
        text = FileReader().read_file(Path(path))
        if len(text) > cfg.document_parser_max_output_chars:
            raise DocumentProcessingError("Извлечённый текст превышает лимит")
        sender.send(("ok", text))
    except BaseException as exc:
        sender.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()


def read_document_isolated(path: Path) -> str:
    """Parse one document in a disposable, resource-limited child process."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(str(path), sender), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(cfg.document_parser_timeout_seconds):
            raise DocumentProcessingTimeoutError("Превышено время обработки документа")
        status, payload = receiver.recv()
        if status != "ok":
            raise DocumentProcessingError(
                f"Не удалось безопасно обработать документ: {payload}"
            )
        return str(payload)
    except EOFError as exc:
        raise DocumentProcessingError("Процесс обработки документа завершился") from exc
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
