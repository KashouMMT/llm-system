from app.memory.short_term_memory import ShortTermMemory
from app.memory.summary_memory import SummaryMemory
from app.memory.vector_memory import VectorMemory

from app.utils.logger import logger

class MemoryRouter:
    def __init__(self, llm, vector_db=None):
        self.short_term = ShortTermMemory()
        self.summary = SummaryMemory(llm)
        self.vector = VectorMemory(vector_db)
        
    def get_session_history(self, session_id: str):
        logger.debug(f"Memory Router | session={session_id}")
        history = self.short_term.get_history(session_id)
        history = self.summary.compress_if_needed(history)
        return history