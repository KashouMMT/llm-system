async def run_cli(application):
    
    session_id = "default"
    
    print("Chat started")
    print("Type /exit to quit")
    print("Type /history to view chat history")
    print("Type /summary to view summary")
    
    while True:
        user_input = input("You: ")
        
        command = user_input.strip().lower()
        
        if command == "/exit":
            print("Goodbye")
            break
        
        if command == "/history":
            messages = application.message_repository.get_messages(
                session_id
            )
            
            print("\n=== Chat History ===")
            
            if not messages:
                print("No message found")
                
            for row in messages:
                _, role, content, created_at = row
                
                print(
                    f"[{created_at}] "
                    f"{role.upper()}: "
                    f"{content}"
                )
            
            print("====================\n")
            
            continue
        
        if command == "/summary":
            summary = (
                application.memory
                .summary_repository
                .get_current_summary(session_id)
            )

            print("\n=== Summary ===")

            if not summary:
                print("No summary found")
            else:
                print(summary)

            print("================\n")

            continue
        
        async for token in application.chat_service.chat_stream(
            user_input=user_input,
            session_id=session_id
        ):
            print(token, end="", flush=True)

        print()