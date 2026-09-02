from app.authentication.models import User

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_ROOT = "root"

ROLES = (ROLE_USER, ROLE_ADMIN, ROLE_ROOT)

# Actions
ACTION_EDIT_SETTINGS = "edit_settings"
ACTION_MANAGE_ADMINS = "manage_admins"


def is_admin(user: User) -> bool:
    return user.role in (ROLE_ADMIN, ROLE_ROOT)


def can(user: User, action: str) -> bool:
    if action == ACTION_EDIT_SETTINGS:
        return user.role in (ROLE_ADMIN, ROLE_ROOT)

    if action == ACTION_MANAGE_ADMINS:
        return user.role == ROLE_ROOT

    return False
