from app.database.connection import get_connection
from app.utils.logger import logger

class MessageRepository:
    
    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ):
        conn = get_connection()
        
        try: 
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO messages (
                        session_id,
                        role,
                        content
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        session_id,
                        role,
                        content
                    )
                )
                
                conn.commit()
                
                logger.debug(f"Message saved | session={session_id} role={role}")
            
        finally:
            conn.close()
            
    def get_messages(
        self,
        session_id: str
    ):
        
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                
                curr.execute(
                    """
                    SELECT
                        id,
                        role,
                        content,
                        created_at
                    FROM messages
                    WHERE session_id = %s
                    ORDER BY id ASC
                    """,
                    (session_id,)
                )
                
                rows = curr.fetchall()
                
                logger.debug(f"Loaded {len(rows)} messages | session={session_id}")
                
                return rows
            
        finally:
            conn.close()
            
    def get_messages_after_id(
        self,
        session_id: str,
        message_id: int  
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                curr.execute(
                """
                SELECT 
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE session_id = %s
                AND id > %s
                ORDER BY id ASC
                """,
                    (
                        session_id,
                        message_id
                    )
                )
                
                rows = curr.fetchall()
                
                logger.debug(f"Loaded {len(rows)} unsummarized messages | session={session_id}")
                
                return rows
            
        finally:
            conn.close()
            
    
    def get_latest_message_id(
        self,
        session_id: str,
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                
                curr.execute(
                """
                SELECT COALESCE(MAX(id), 0)
                FROM messages
                WHERE session_id = %s
                """,
                    (
                        session_id,
                    )
                )
                
                result = curr.fetchone()
                
                return result[0]
                
        finally:
            conn.close()
            
    def get_recent_messages(
        self,
        session_id: str,
        limit: int = 20
    ):
        conn = get_connection()
        
        try:
            with conn.cursor() as curr:
                
                curr.execute(
                """
                SELECT
                    id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE session_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                    (
                        session_id,
                        limit
                    )
                )
                
                rows = curr.fetchall()
                
                rows.reverse()
                
                logger.debug(f"Loaded {len(rows)} recent messages | session={session_id}")
                
                return rows
                
        finally:
            conn.close()