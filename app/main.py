import asyncio

from app.persona.system_prompt_builder import build_system_prompt

from app.llm.llm_factory import LLMFactory
from app.llm.prompt_factory import PromptFactory
from app.llm.chain_factory import ChainFactory
from app.memory.memory_router import MemoryRouter
from app.services.chat_service import ChatService

async def run_chat():
    system_prompt = build_system_prompt()
    llm = LLMFactory.create()
    prompt = PromptFactory.create(system_prompt)
    memory = MemoryRouter(llm)
    chain = ChainFactory.create(prompt, llm, memory)
    chat_service = ChatService(chain, memory, system_prompt)
    
    while True:
        user_input = input("You: ")
        if user_input == "/exit":
            break
        
        async for token in chat_service.chat_stream(user_input):
            print(token, end="", flush=True)
        print()

def main():
    asyncio.run(run_chat())

if __name__ == "__main__":
    main()