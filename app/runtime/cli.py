async def run_cli(application):
    print("Chat started")
    print("Type /exit to quit")
    
    while True:
        user_input = input("You: ")
        
        if user_input.strip().lower() == "/exit":
            print("Goodbye")
            break
        
        async for token in application.chat_service.chat_stream(
            user_input=user_input
        ):
            print(token, end="", flush=True)

        print()