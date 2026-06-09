from app.persona.load_prompt import load_prompt

from app.llm.llm_factory import LLMFactory
from app.llm.prompt_factory import PromptFactory
from app.llm.chain_factory import ChainFactory

from app.memory.memory_router import MemoryRouter

from app.services.chat_service import ChatService

from app.database.init_db import initialize_database


class Application:
    def __init__(self):
        initialize_database()
        self.system_prompt = load_prompt()
        self.llm = LLMFactory.create()
        self.memory = MemoryRouter(self.llm)
        self.prompt = PromptFactory.create(self.system_prompt)
        self.chain = ChainFactory.create(
            self.prompt,
            self.llm,
            self.memory
        )
        
        self.chat_service = ChatService(
            self.chain,
            self.memory,
            self.system_prompt
        )
        
def create_application():
    return Application()