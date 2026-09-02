import asyncio
from dataclasses import fields
from uuid import UUID, uuid4

from app.config.runtime_settings import (
    FIELD_PARSERS,
    PERSISTED_FIELDS,
    RuntimeSettings,
)
from app.runtime.application import Application
from app.runtime.event_bus import EVENT_MESSAGE_DELTA
from app.services.chat_service import TERMINAL_EVENTS
from app.utils.logger import logger


async def select_conversation(
    application: Application,
    user_id: UUID,
) -> UUID:

    conversations = await application.conversation_repository.get_conversations(
        user_id,
    )

    print("\n=== Conversations ===")

    if not conversations:
        print("No existing conversations found.")
        print("Starting a new conversation...")

        conversation_id = await application.conversation_repository.create_conversation(
            user_id=user_id,
        )

        print(f"Conversation: {conversation_id}")

        return conversation_id

    for index, conversation in enumerate(conversations, start=1):
        print(
            f"{index}. "
            f"{conversation.title or 'Untitled conversation'} "
            f"(created: {conversation.created_at})"
            f"(updated: {conversation.updated_at})"
        )

    print()
    print("n. New conversation")
    print("q. Quit")

    while True:
        choice = input("Select a conversation: ").strip().lower()

        if choice == "q":
            raise SystemExit

        if choice == "n":
            conversation_id = (
                await application.conversation_repository.create_conversation(
                    user_id=user_id,
                )
            )

            print("\nNew conversation created.")
            print(f"Conversation: {conversation_id}")

            return conversation_id

        try:
            index = int(choice)

        except ValueError:
            print("Invalid selection. Please enter a number, 'n', or 'q'.")
            continue

        if index < 1 or index > len(conversations):
            print("Invalid conversation number.")
            continue

        conversation_id = conversations[index - 1].id

        print(f"\nResuming conversation: {conversation_id}")

        return conversation_id


async def print_history(
    application: Application,
    conversation_id: UUID,
) -> None:

    messages = await application.message_repository.get_messages(
        conversation_id,
    )

    print("\n=== Chat History ===")

    if not messages:
        print("No messages found.")

    for message in messages:
        marker = "" if message.status == "complete" else f" [{message.status}]"

        print(
            f"[{message.created_at}] {message.role.upper()}{marker}: {message.content}"
        )

    print("====================\n")


def print_settings(application: Application) -> None:
    """
    Show every runtime-adjustable setting and how long a change to it lasts.

    The scope column is the point of this view: a persisted setting
    survives a restart, a session one does not.
    """
    settings = application.runtime_settings.current
    defaults = RuntimeSettings.from_env()

    print("\n=== Runtime Settings ===")

    for field in fields(settings):
        name = field.name
        value = getattr(settings, name)
        scope = "persisted" if name in PERSISTED_FIELDS else "session"

        # Marked so it is obvious which values are no longer the ones the
        # environment supplied.
        changed = " *" if value != getattr(defaults, name) else ""

        print(f"  {name:<30} {value!r:<12} [{scope}]{changed}")

    print()
    print("  * differs from the environment default")
    print("  /set <key> <value>   change a setting")
    print("  /reset <key>         restore the environment default")
    print("========================\n")


async def set_setting(application: Application, argument: str) -> None:
    parts = argument.split(maxsplit=1)

    if len(parts) != 2:
        print("Usage: /set <key> <value>")
        return

    key, value = parts

    try:
        await application.apply_settings({key: value})

    except ValueError as error:
        print(f"[rejected] {error}")
        return

    current = getattr(application.runtime_settings.current, key)
    scope = "persisted" if key in PERSISTED_FIELDS else "this session only"

    print(f"{key} = {current!r} ({scope})")


async def reset_setting(application: Application, key: str) -> None:
    """
    Restore a setting to its environment default and drop any stored row.

    Both halves matter: without the delete the old override would come
    back on the next start, because the database layers over the
    environment.
    """
    if key not in FIELD_PARSERS:
        print(f"[rejected] Unknown or non-editable setting: {key}")
        return

    default = getattr(RuntimeSettings.from_env(), key)

    try:
        await application.apply_settings({key: default})

    except ValueError as error:
        print(f"[rejected] {error}")
        return

    if key in PERSISTED_FIELDS:
        await application.settings_repository.delete(key)

    print(f"{key} = {default!r} (restored from environment)")


async def run_cli(
    application: Application,
) -> None:

    root = await application.user_repository.get_root()

    if root is None:
        raise RuntimeError(
            "No root user exists. Set AUTH_BOOTSTRAP_USERNAME / "
            "AUTH_BOOTSTRAP_PASSWORD and restart, or run with --seed-admin.",
        )

    conversation_id = await select_conversation(application, root.id)

    print()
    print("Chat started")
    print(f"Conversation: {conversation_id}")
    print()
    print("Type /exit to quit")
    print("Type /history to view chat history")
    print("Type /settings to view runtime settings")
    print("Type /set <key> <value> to change one, /reset <key> to restore it")
    print()

    while True:
        user_input = await asyncio.to_thread(input, "You: ")

        # Case is preserved for arguments — persona names and log levels
        # are values, not commands.
        stripped = user_input.strip()
        command = stripped.lower()

        if not stripped:
            continue

        if command == "/exit":
            print("Goodbye")

            break

        if command == "/history":
            await print_history(application, conversation_id)

            continue

        if command == "/settings":
            print_settings(application)

            continue

        if command.startswith("/set "):
            await set_setting(application, stripped[len("/set ") :])

            continue

        if command.startswith("/reset "):
            await reset_setting(application, stripped[len("/reset ") :].strip())

            continue

        if application.chat_service is None:
            raise RuntimeError("Application has not been initialized.")

        if not application.conversation_lock.try_acquire(conversation_id):
            print("\n[busy] A response is already being generated.")
            continue

        generation = None

        try:
            async with application.event_bus.subscribe(
                conversation_id,
            ) as subscription:
                turn = await application.chat_service.begin_turn(
                    conversation_id=conversation_id,
                    user=root,
                    user_input=user_input,
                    client_message_id=uuid4(),
                )

                generation = application.spawn(
                    application.chat_service.generate(
                        conversation_id=conversation_id,
                        user_message_id=turn.user_message_id,
                        assistant_message_id=turn.assistant_message_id,
                        user_input=user_input,
                    )
                )

                while True:
                    event = await subscription.next_event(timeout=1.0)

                    if event is None:
                        if generation.done():
                            break
                        continue

                    if event.payload.get("message_id") != turn.assistant_message_id:
                        continue

                    if event.type == EVENT_MESSAGE_DELTA:
                        print(event.payload["text"], end="", flush=True)

                    elif event.type in TERMINAL_EVENTS.values():
                        status = event.payload["status"]

                        if status != "complete":
                            print(f"\n[{status}]")

                        break

                print()

        except Exception:  # noqa: BLE001
            # Only ours to release if generation never started. Once it
            # has, _finalize owns the lock — releasing here would let a
            # second run start on the same checkpoint thread.
            if generation is None:
                application.conversation_lock.release(conversation_id)

            logger.warning("Chat request failed; returning to prompt")
            print(
                "\n[error] The request failed. "
                "Your conversation is intact — please try again."
            )
