# scripts/create_admin.py
"""
Create an admin account (production databases are not seeded with demo users).

Usage:
    python scripts/create_admin.py --email admin@yourschool.com --username admin \
        --first-name Ada --last-name Admin --phone +2348000000000
The password is prompted for (or read from ADMIN_PASSWORD).
"""
import argparse
import asyncio
import getpass
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import or_  # noqa: E402
from sqlmodel import select  # noqa: E402

from app.core.database import AsyncSessionFactory, async_engine  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models import Gender, User, UserRole  # noqa: E402


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--phone", required=True)
    args = parser.parse_args()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    async with AsyncSessionFactory() as session:
        existing = (await session.execute(select(User).where(or_(
            User.email == args.email, User.username == args.username, User.phone == args.phone
        )))).scalars().first()
        if existing:
            sys.exit(f"A user with that email, username or phone already exists ({existing.email}).")
        session.add(User(
            username=args.username, email=args.email, phone=args.phone,
            password_hash=await get_password_hash(password), role=UserRole.admin,
            first_name=args.first_name, last_name=args.last_name,
            gender=Gender.other, date_of_birth=date(1980, 1, 1),
        ))
        await session.commit()
    await async_engine.dispose()
    print(f"Admin {args.email} created.")


if __name__ == "__main__":
    asyncio.run(main())
