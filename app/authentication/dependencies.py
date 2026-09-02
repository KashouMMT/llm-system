from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.authentication.authorization import is_admin
from app.authentication.models import User
from app.config.settings import SESSION_COOKIE_NAME
from app.runtime.application import Application


def make_current_user(application: Application):
    """Resolve the session cookie to a User, or raise 401."""

    async def current_user(request: Request) -> User:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        user = await application.auth_service.resolve(token)

        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        return user

    return current_user


def make_require_admin(current_user):
    """Require an admin or root user, or raise 403."""

    async def require_admin(
        user: Annotated[User, Depends(current_user)],
    ) -> User:
        if not is_admin(user):
            raise HTTPException(
                status_code=403,
                detail="Administrator privileges required",
            )
        return user

    return require_admin
