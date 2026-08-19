from langchain_core.chat_history import BaseChatMessageHistory

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage
)

from app.config.settings import MAX_UNSUMMARIZED_MESSAGES

from app.repositories.message_repository import MessageRepository
from app.repositories.summary_repository import SummaryRepository

from app.utils.logger import logger

class ChatHistory(BaseChatMessageHistory):
    
    def __init__(
        self,
        session_id: str,
        repository: MessageRepository,
        summary_repository: SummaryRepository
    ):
        self.session_id = session_id
        self.repository = repository
        self.summary_repository = summary_repository
        
    @property
    def messages(self):
        
        summary = (self.summary_repository.get_current_summary(self.session_id))
        
        logger.debug(f"Summary loaded | chars={len(summary)}")
        
        last_summarized_id = (
            self.summary_repository
            .get_last_summarized_message_id(
                self.session_id
            )
        )
        
        rows = self.repository.get_messages_after_id(
            self.session_id,
            last_summarized_id
        )
        
        rows = rows[-MAX_UNSUMMARIZED_MESSAGES:]
        
        logger.debug(f"Unsummarized messages loaded | count={len(rows)}")
        
        result = []
        
        if summary:
            result.append(
                SystemMessage(
                    content=f"""
Conversation Summary:

{summary}
"""
                )
            )
        
        for _, role, content, _ in rows:
            if role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
                   
        return result

    def add_message(self, message):
        """
        Persistence is handled by ChatService.
        RunnableWithMessageHistory still requires
        this method to exist.
        """
        pass
    
    def clear(self):
        """
        Not implemented yet.
        """
        pass
        