import secrets

from app.authentication.authorization import ROLE_ROOT
from app.authentication.passwords import hash_password
from app.repositories.user_repository import UserRepository
from app.utils.logger import logger


async def seed_root(
    user_repository: UserRepository,
    *,
    username: str,
    password: str,
    force: bool = False,
) -> None:
    """
    Ensure the single root user exists.

    Precedence:
      1. Root already exists and force is False -> do nothing.
      2. AUTH_BOOTSTRAP_USERNAME / _PASSWORD set -> use them.
      3. Otherwise generate a random password, so the system is never
         left with no way in. It is logged once, at WARNING, and can be
         replaced by setting the environment variables and restarting, or
         by running with --seed-admin.
    """
    existing = await user_repository.get_root()

    if existing is not None and not force:
        logger.info("Root user already exists | username=%s", existing.username)
        return

    resolved_username = (username or "root").strip().lower()

    if password:
        resolved_password = password
        generated = False
    else:
        resolved_password = secrets.token_urlsafe(24)
        generated = True

    password_hash = hash_password(resolved_password)

    if existing is None:
        await user_repository.create(resolved_username, password_hash, ROLE_ROOT)
        action = "created"
    else:
        await user_repository.update_root_credentials(
            existing.id,
            resolved_username,
            password_hash,
        )
        action = "reset"

    if generated:
        logger.warning(
            "Root user %s with a GENERATED password | username=%s password=%s | "
            "set AUTH_BOOTSTRAP_USERNAME / AUTH_BOOTSTRAP_PASSWORD or run "
            "--seed-admin to replace it",
            action,
            resolved_username,
            resolved_password,
        )
    else:
        logger.info(
            "Root user %s from environment | username=%s",
            action,
            resolved_username,
        )
