import asyncio
from uuid import UUID

from app.runtime.application import Application
from app.utils.logger import logger


def select_conversation(
    application: Application,
) -> UUID:

    conversations = application.conversation_repository.get_conversations()

    print("\n=== Conversations ===")

    if not conversations:
        print("No existing conversations found.")
        print("Starting a new conversation...")

        conversation_id = application.conversation_repository.create_conversation()

        print(f"Conversation: {conversation_id}")

        return conversation_id

    for index, row in enumerate(conversations, start=1):
        conversation_id = row[0]
        title = row[1]
        created_at = row[2]
        updated_at = row[3]

        print(
            f"{index}. "
            f"{title or 'Untitled conversation'} "
            f"(created: {created_at})"
            f"(updated: {updated_at})"
        )

    print()
    print("n. New conversation")
    print("q. Quit")

    while True:
        choice = input("Select a conversation: ").strip().lower()

        if choice == "q":
            raise SystemExit

        if choice == "n":
            conversation_id = application.conversation_repository.create_conversation()

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


def print_history(
    application: Application,
    conversation_id: UUID,
) -> None:

    messages = application.message_repository.get_messages(conversation_id)

    print("\n=== Chat History ===")

    if not messages:
        print("No messages found.")

    for row in messages:
        _, role, content, created_at = row

        print(f"[{created_at}] {role.upper()}: {content}")

    print("====================\n")


async def run_cli(
    application: Application,
) -> None:

    conversation_id = select_conversation(application)

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
            print_history(application, conversation_id)

            continue

        if application.chat_service is None:
            raise RuntimeError("Application has not been initialized.")

        try:
            async for token in application.chat_service.chat_stream(
                user_input=user_input,
                conversation_id=conversation_id,
            ):
                print(
                    token,
                    end="",
                    flush=True,
                )

            print()

        except Exception:  # noqa: BLE001
            # ChatService already logged the traceback with request context.
            logger.warning("Chat request failed; returning to prompt")
            print(
                "\n[error] The request failed. "
                "Your conversation is intact — please try again."
            )
