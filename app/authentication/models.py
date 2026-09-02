from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class User:
    id: UUID
    username: str
    password_hash: str
    role: str
    created_at: datetime
    updated_at: datetime