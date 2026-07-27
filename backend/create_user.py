import argparse
import asyncio
import getpass

from sqlalchemy import select

from backend.db.connector import async_session
from backend.db.models import User
from backend.security import hash_password


async def create_user(username: str, password: str) -> None:
    username = username.strip().lower()
    if not username or len(username) > 150:
        raise ValueError("Логин должен содержать от 1 до 150 символов")
    if len(password) < 8:
        raise ValueError("Пароль должен содержать минимум 8 символов")
    async with async_session() as session:
        if await session.scalar(select(User).where(User.username == username)):
            raise ValueError(f"Пользователь {username!r} уже существует")
        session.add(User(username=username, password_hash=hash_password(password)))
        await session.commit()
    print(f"Пользователь {username!r} создан")


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать пользователя КарьеРадара")
    parser.add_argument("username")
    parser.add_argument(
        "--password", help="Не рекомендуется: пароль попадёт в историю команд"
    )
    args = parser.parse_args()
    password = args.password or getpass.getpass("Пароль: ")
    confirmation = args.password or getpass.getpass("Повторите пароль: ")
    if password != confirmation:
        raise SystemExit("Пароли не совпадают")
    try:
        asyncio.run(create_user(args.username, password))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
