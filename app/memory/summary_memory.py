from langchain_core.messages import HumanMessage

from app.config.settings import (
    SUMMARY_TOKEN_THRESHOLD,
    SUMMARY_CHUNK_PROMPT,
    SUMMARY_MERGE_PROMPT
)

from app.repositories.message_repository import MessageRepository
from app.repositories.summary_repository import SummaryRepository

from app.utils.logger import logger

class SummaryMemory:
    
    def __init__(
        self,
        llm,
        token_threshold: int = SUMMARY_TOKEN_THRESHOLD
    ):
        self.llm = llm
        self.token_threshold = token_threshold
        self.message_repository = MessageRepository()
        self.summary_repository = SummaryRepository()
        
    # This estimate should be tokens. not characters
    def estimate_tokens(
        self,
        text: str,
    ):
        
        result = len(text) // 4
        
        logger.debug(f"Estimated tokens={result}")
        
        return result
    
    def generate_chunk_summary(
        self,
        rows
    ):
        conversation =  "\n".join(
            f"{role}: {content}"
            for _, role, content, _ in rows
        )
        
        prompt = SUMMARY_CHUNK_PROMPT.format(conversation=conversation)
        response = self.llm.invoke([HumanMessage(content=prompt)])
        
        return response.content
    
    def update_master_summary(
        self,
        current_summary: str,
        chunk_summary: str
    ):
        prompt = SUMMARY_MERGE_PROMPT.format(current_summary=current_summary,chunk_summary=chunk_summary)
        response = self.llm.invoke([HumanMessage(content=prompt)])

        return response.content
    
    def summarize(
        self,
        session_id: str
    ):
        rows = self.get_unsummarized_messages(session_id)
        
        if not rows:
            return
        
        chunk_summary = self.generate_chunk_summary(rows)
        
        start_message_id = rows[0][0]
        end_message_id = rows[-1][0]
        
        self.summary_repository.save_summary_chunk(
            session_id=session_id,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            summary=chunk_summary
        )
        
        current_summary = (self.summary_repository.get_current_summary(session_id))
        
        updated_summary = (self.update_master_summary(current_summary,chunk_summary))
        
        self.summary_repository.upsert_summary_state(
            session_id=session_id,
            summary=updated_summary,
            last_summarized_message_id=end_message_id
        )
        
        logger.info(f"Conversation summarized | session={session_id} messages={len(rows)}")
        
    def trigger_if_needed(
        self,
        session_id: str
    ):
        if not self.should_summarize(session_id):
            return
        
        self.summarize(session_id)
        
    def should_summarize(
        self,
        session_id: str
    ):
        rows = self.get_unsummarized_messages(session_id)
        
        logger.debug(f"Unsummarized messages={len(rows)}")
        
        combined_text = "\n".join(
            row[2]
            for row in rows
        )
        
        estimated_tokens = self.estimate_tokens(combined_text)
        
        logger.debug(f"Summary Check | session={session_id}")
        logger.debug(f"tokens={estimated_tokens}")
        
        return (estimated_tokens >= self.token_threshold)
        
    def get_unsummarized_messages(
        self,
        session_id: str,
    ):
        last_id = (self.summary_repository.get_last_summarized_message_id(session_id))
        
        return (self.message_repository.get_messages_after_id(session_id,last_id))