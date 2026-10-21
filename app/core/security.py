from passlib.context import CryptContext
from anyio.to_thread import run_sync

pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')


async def get_password_hash(password: str):
    return await run_sync(pwd_context.hash, password)

async def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return await run_sync(pwd_context.verify, plain_password, hashed_password)