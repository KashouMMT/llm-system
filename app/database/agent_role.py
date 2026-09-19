"""
The database role model-written SQL runs as, and the only way it runs.

A plugin that lets the model query its data (recycling's catalog analysis)
does not get the application's own pool for that. The application logs in
as DB_USER, which is a superuser locally; SQL the model wrote, run on that
connection, could read `users` and `sessions` or rewrite anything. Instead:

- **Core owns the role.** `AgentRole` creates a separate LOGIN role
  (DB_AGENT_USER) with no table grants at all, and a small pool that logs
  in *as* it. A separate login, never `SET ROLE` on the main pool: a
  superuser session can always `RESET ROLE` back, and the model's SQL
  could do it.
- **Plugins grant their own tables.** `grant_select(relation)` gives the
  role SELECT on one table or view. Core never needs to know what plugins
  store, and a plugin can only open up what it owns.
- **Lazy.** The role is created the first time a plugin asks for a grant.
  A deployment where no plugin asks (the job-application server excludes
  recycling) never gets a login role it does not use.

`query()` is the single path for model-written SQL. The role's grants are
the guard; everything else is depth behind it, each layer measured
against a real server before it was relied on:

- The SQL is wrapped as `SELECT * FROM (<sql>) AS agent_query LIMIT n`.
  That makes a second statement a syntax error, rejects a data-modifying
  `WITH` (Postgres refuses one inside a subquery), rejects SET/SHOW, and
  applies the row cap inside the database — cheap however large the table.
- A READ ONLY transaction, so no write can happen even through a function.
- `statement_timeout`, so a runaway join or pg_sleep ends.
- A character cap on the text handed back, since a row cap alone does not
  bound a result with wide columns.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from app.utils.logger import logger

QUERY_TIMEOUT_MS = 5000
_POOL_OPEN_TIMEOUT_SECONDS = 10.0


class AgentQueryError(RuntimeError):
    """The query was rejected or failed. The message is written for the
    model to read and correct its SQL — a syntax error, an unknown column,
    permission denied, the time limit."""


@dataclass(frozen=True)
class AgentQueryResult:
    columns: list[str]
    rows: list[tuple]
    # True when rows were cut, by the row cap or the character cap.
    truncated: bool
    # The row cap that applied, so the text can say "first N rows".
    max_rows: int

    def as_text(self, max_chars: int) -> str:
        """
        The rows as pipe-separated lines for the model: a header, then one
        line per row, NULL spelled out so it is never mistaken for an empty
        string. Cut at max_chars, and the cut is stated — a model that does
        not know it saw a partial result will report it as the whole.
        """
        lines = [" | ".join(self.columns)]
        used = len(lines[0])
        shown = 0

        for row in self.rows:
            line = " | ".join(_cell(value) for value in row)

            if used + len(line) + 1 > max_chars:
                break

            lines.append(line)
            used += len(line) + 1
            shown += 1

        cut = self.truncated or shown < len(self.rows)

        if not self.rows:
            lines.append("(no rows)")
        elif cut:
            lines.append(
                f"(result cut after {shown} row(s): the query returned more than "
                f"fits — at most {self.max_rows} rows or {max_chars} characters. "
                "Aggregate with COUNT/GROUP BY, select fewer columns, or page "
                "with LIMIT/OFFSET.)"
            )
        else:
            lines.append(f"({shown} row(s))")

        return "\n".join(lines)


def _cell(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        return f"{value:g}"
    # Newlines and the separator would break the one-row-per-line shape.
    return str(value).replace("\n", " ").replace("|", "/")


class AgentRole:
    def __init__(
        self,
        *,
        admin_pool: AsyncConnectionPool,
        conninfo: str,
        role: str,
        password: str,
        default_password: str,
        main_user: str,
        database: str,
    ) -> None:
        # admin_pool is the application's own pool: role DDL and grants
        # need its privileges. Queries never touch it.
        self._admin_pool = admin_pool
        self._role = role
        self._password = password
        self._default_password = default_password
        self._main_user = main_user
        self._database = database
        self._pool = AsyncConnectionPool(
            conninfo=make_conninfo(conninfo, user=role, password=password),
            min_size=1,
            max_size=2,
            open=False,
        )
        # None until the first grant: not yet decided. Then True/False.
        self._ready: bool | None = None

    @property
    def configured(self) -> bool:
        """Whether model-written SQL is allowed at all on this deployment.
        An empty DB_AGENT_PASSWORD switches it off."""
        return bool(self._password)

    @property
    def ready(self) -> bool:
        return bool(self._ready)

    async def grant_select(self, relation: str) -> bool:
        """
        Give the agent role SELECT on one table or view. Called by a plugin
        from its initialize hook, for a relation it owns. Creates the role
        and opens its pool on the first call.

        Returns False when agent SQL is unavailable — switched off, or the
        role could not be set up. The plugin keeps loading; only its query
        tool is affected, and it says so when called.
        """
        if not await self._ensure_ready():
            return False

        try:
            async with self._admin_pool.connection() as conn:
                await conn.execute(
                    sql.SQL("GRANT SELECT ON {} TO {}").format(
                        sql.Identifier(relation), sql.Identifier(self._role)
                    )
                )
        except psycopg.Error:
            logger.exception(
                "Agent role grant failed | role=%s relation=%s", self._role, relation
            )
            return False

        logger.info("Agent role granted | role=%s relation=%s", self._role, relation)
        return True

    async def _ensure_ready(self) -> bool:
        if self._ready is not None:
            return self._ready

        self._ready = False

        if not self.configured:
            logger.info("Agent SQL disabled | reason=DB_AGENT_PASSWORD is empty")
            return False

        # Refused outright rather than altered: pointing DB_AGENT_USER at
        # the application's own login would hand the model the main role.
        if self._role == self._main_user:
            logger.error(
                "Agent SQL disabled | reason=DB_AGENT_USER equals DB_USER (%s); "
                "it must be a separate role",
                self._role,
            )
            return False

        try:
            await self._create_or_update_role()
        except _UnsafeRoleError as exc:
            logger.error("Agent SQL disabled | reason=%s", exc)
            return False
        except psycopg.Error:
            logger.exception("Agent SQL disabled | reason=role setup failed role=%s", self._role)
            return False

        try:
            await self._pool.open(wait=True, timeout=_POOL_OPEN_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Agent SQL disabled | reason=could not log in as role=%s", self._role
            )
            return False

        if self._password == self._default_password:
            logger.warning(
                "Agent SQL is using the built-in default DB_AGENT_PASSWORD. Fine "
                "locally; set a real one in .env for any shared server."
            )

        self._ready = True
        logger.info("Agent SQL ready | role=%s", self._role)
        return True

    async def _create_or_update_role(self) -> None:
        role = sql.Identifier(self._role)

        async with self._admin_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                "FROM pg_roles WHERE rolname = %s",
                (self._role,),
            )
            existing = await cur.fetchone()

            if existing is None:
                # Postgres defaults are already NOSUPERUSER NOCREATEDB
                # NOCREATEROLE. Not spelled out: on RDS the master user may
                # not name the SUPERUSER attribute at all, even to deny it.
                await conn.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        role, sql.Literal(self._password)
                    )
                )
                logger.info("Agent role created | role=%s", self._role)
            elif any(existing):
                raise _UnsafeRoleError(
                    f"role {self._role} already exists with elevated privileges "
                    "(superuser, createrole, createdb or bypassrls); refusing to "
                    "run model-written SQL as it"
                )
            else:
                # Every start, so a changed DB_AGENT_PASSWORD takes effect.
                await conn.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        role, sql.Literal(self._password)
                    )
                )

            # Defaults for every session the role opens; query() also sets
            # both per transaction, these are the backstop.
            await conn.execute(
                sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role)
            )
            await conn.execute(
                sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
                    role, sql.Literal(f"{QUERY_TIMEOUT_MS}ms")
                )
            )
            await conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(self._database), role
                )
            )
            await conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))

    async def query(self, text: str, *, max_rows: int) -> AgentQueryResult:
        """
        Run one model-written read-only query. Raises AgentQueryError with a
        message the model can act on; never returns a partial result
        silently (see AgentQueryResult.truncated).
        """
        if not self.ready:
            raise AgentQueryError(
                "Database queries are not available on this server "
                "(the agent database role is disabled or failed to start)."
            )

        # Trailing semicolons would end the wrapper early; everything else
        # is left exactly as written. The newline before ")" keeps a
        # trailing `-- comment` from swallowing the closing parenthesis.
        body = text.strip().rstrip(";").strip()

        if not body:
            raise AgentQueryError("The query is empty.")

        wrapped = f"SELECT * FROM (\n{body}\n) AS agent_query LIMIT {max_rows + 1}"

        try:
            async with self._pool.connection() as conn, conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}")
                # No parameters, so `%` in the model's LIKE patterns is sent
                # as written. prepare=True sends it through Parse, which
                # refuses more than one statement even if the wrapper did not.
                cur = await conn.execute(wrapped, prepare=True)
                rows = await cur.fetchall()
                columns = [column.name for column in cur.description or []]
        except psycopg.Error as exc:
            # A warning, not an exception trace: a model writing a bad query
            # is expected, and it gets the message to fix it.
            message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            logger.warning(
                "Agent query failed | role=%s error=%s: %s",
                self._role,
                type(exc).__name__,
                message,
            )
            raise AgentQueryError(f"{type(exc).__name__}: {message}") from exc

        return AgentQueryResult(
            columns=columns,
            rows=rows[:max_rows],
            truncated=len(rows) > max_rows,
            max_rows=max_rows,
        )

    async def close(self) -> None:
        await self._pool.close()


class _UnsafeRoleError(RuntimeError):
    pass
