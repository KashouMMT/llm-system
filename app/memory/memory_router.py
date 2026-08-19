from app.memory.chat_history import ChatHistory
from app.memory.summary_memory import SummaryMemory
from app.memory.vector_memory import VectorMemory
from app.repositories.message_repository import MessageRepository
from app.repositories.summary_repository import SummaryRepository

from app.utils.logger import logger

class MemoryRouter:
    def __init__(self, llm, vector_db=None):
        self.repository = MessageRepository()
        self.summary = SummaryMemory(llm)
        self.summary_repository = SummaryRepository()
        self.vector = VectorMemory(vector_db)
        
    def get_session_history(
        self, 
        session_id: str
    ):
        
        logger.debug(f"Memory Router | session={session_id}")
        
        history = ChatHistory(
            session_id=session_id,
            repository=self.repository,
            summary_repository=self.summary_repository
        )
        
        return history