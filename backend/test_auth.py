import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from backend.api.v1.auth import login


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_success_response_before_transaction_rollback(self) -> None:
        events: list[str] = []
        user = SimpleNamespace(
            id="12345678-1234-5678-1234-567812345678",
            username="alice",
            password_hash="encoded",
            is_active=True,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=user),
            rollback=AsyncMock(side_effect=lambda: events.append("rollback")),
        )
        request = Request(
            {"type": "http", "client": ("127.0.0.1", 12345), "headers": []}
        )
        form = SimpleNamespace(username="Alice", password="correct")

        def create_token(_user) -> str:
            events.append("token")
            return "signed-token"

        with (
            patch("backend.api.v1.auth.lock_attempt_buckets", new=AsyncMock()),
            patch(
                "backend.api.v1.auth.recent_failure_counts",
                new=AsyncMock(return_value=(0, 0)),
            ),
            patch("backend.api.v1.auth.verify_password", return_value=True),
            patch("backend.api.v1.auth.create_access_token", side_effect=create_token),
        ):
            response = await login(request=request, form=form, session=session)

        self.assertEqual(events, ["token", "rollback"])
        self.assertEqual(
            response,
            {
                "access_token": "signed-token",
                "token_type": "bearer",
                "username": "alice",
            },
        )


if __name__ == "__main__":
    unittest.main()
