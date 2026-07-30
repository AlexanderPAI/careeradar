import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.datastructures import UploadFile

from backend.request_limits import RequestBodyLimitMiddleware
from backend.resume_storage import UploadTooLargeError, save_upload


class RequestBodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_declared_oversized_body_before_endpoint(self) -> None:
        endpoint_called = False

        async def endpoint(scope, receive, send) -> None:
            nonlocal endpoint_called
            endpoint_called = True

        middleware = RequestBodyLimitMiddleware(endpoint, max_bytes=5)
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "headers": [(b"content-length", b"6")],
            },
            receive,
            send,
        )

        self.assertFalse(endpoint_called)
        self.assertEqual(sent[0]["status"], 413)

    async def test_rejects_chunked_body_as_soon_as_limit_is_exceeded(self) -> None:
        chunks = iter(
            (
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            )
        )

        async def endpoint(scope, receive, send) -> None:
            while True:
                message = await receive()
                if not message.get("more_body", False):
                    break

        middleware = RequestBodyLimitMiddleware(endpoint, max_bytes=5)
        sent: list[dict] = []

        async def receive() -> dict:
            return next(chunks)

        async def send(message: dict) -> None:
            sent.append(message)

        await middleware({"type": "http", "headers": []}, receive, send)
        self.assertEqual(sent[0]["status"], 413)

    async def test_partial_upload_is_removed_when_file_limit_is_exceeded(self) -> None:
        upload = UploadFile(io.BytesIO(b"123456"), filename="resume.txt")
        with tempfile.TemporaryDirectory() as directory:
            upload_dir = Path(directory)
            with patch("backend.resume_storage.UPLOAD_DIR", upload_dir):
                with self.assertRaises(UploadTooLargeError):
                    await save_upload(upload, "resume.txt", max_bytes=5)
            self.assertEqual(list(upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
