from app.database.connection import get_connection
from app.utils.logger import logger

class SummaryRepository:
    
    def get_summary_state(
        self,
        session_id: str
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                
                curr.execute(
                """
                SELECT 
                    summary,
                    last_summarized_message_id
                FROM conversation_summary_state
                WHERE session_id = %s
                """,
                    (
                        session_id,
                    )
                )
                
                return curr.fetchone()
                
        finally:
            conn.close()
            
    def get_current_summary(
        self,
        session_id: str,
    ):
        state = self.get_summary_state(session_id)
        
        if state is None:
            return ""
        
        summary, _ = state
        
        return summary
            
    def get_last_summarized_message_id(
        self,
        session_id: str
    ):
        state = self.get_summary_state(session_id)
        
        if state is None:
            return 0
        
        _, last_message_id = state
        
        return last_message_id
    
    def upsert_summary_state(
        self,
        session_id: str,
        summary: str,
        last_summarized_message_id: int
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                curr.execute(
                """
                INSERT INTO conversation_summary_state (
                    session_id,
                    summary,
                    last_summarized_message_id
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id)
                DO UPDATE SET
                    summary = EXCLUDED.summary,
                    last_summarized_message_id = EXCLUDED.last_summarized_message_id,
                    updated_at = NOW()
                """,
                    (
                        session_id,
                        summary,
                        last_summarized_message_id,
                    )
                )
                
                conn.commit()

                logger.debug(f"Summary state updated | session={session_id}")
                
        finally:
            conn.close()
            
        
    def save_summary_chunk(
        self,
        session_id: str,
        start_message_id: int,
        end_message_id: int,
        summary: str
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                curr.execute(
                """
                INSERT INTO conversation_summaries (
                    session_id,
                    start_message_id,
                    end_message_id,
                    summary
                )
                VALUES (%s, %s, %s, %s)
                """,
                    (
                        session_id,
                        start_message_id,
                        end_message_id,
                        summary
                    )
                )
                
                conn.commit()
                
                logger.debug(f"Summary chunk saved | session={session_id}")
                
        finally:
            conn.close()