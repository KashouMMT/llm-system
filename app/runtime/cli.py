import asyncio
from uuid import UUID, uuid4

from app.runtime.application import Application
from app.runtime.event_bus import EVENT_MESSAGE_DELTA
from app.services.chat_service import TERMINAL_EVENTS
from app.utils.logger import logger


async def select_conversation(
    application: Application,
) -> UUID:

    conversations = await application.conversation_repository.get_conversations()

    print("\n=== Conversations ===")

    if not conversations:
        print("No existing conversations found.")
        print("Starting a new conversation...")

        conversation_id = (
            await application.conversation_repository.create_conversation()
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
            await application.conversation_repository.create_conversation()
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
            f"[{message.created_at}] "
            f"{message.role.upper()}{marker}: {message.content}"
        )

    print("====================\n")


async def run_cli(
    application: Application,
) -> None:

    conversation_id = await select_conversation(application)

    print()
    print("Chat started")
    print(f"Conversation: {conversation_id}")
    print()
    print("Type /exit to quit")
    print("Type /history to view chat history")
    print()

    while True:
        user_input = await asyncio.to_thread(input, "You: ")

        command = user_input.strip().lower()

        if command == "/exit":
            print("Goodbye")

            break

        if command == "/history":
            await print_history(application, conversation_id)

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
