import psycopg

from app.config.settings import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD
)

from app.utils.logger import logger
from app.database.connection import get_connection

def create_db_if_not_exist():
    conn = psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname="postgres",
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM pg_database
                WHERE datname = %s
                """,
                (DB_NAME,)
            )
            
            exists = cur.fetchone()
            
            if exists:
                logger.info(f"Database already exists: {DB_NAME}")
                return
            
            cur.execute(f"CREATE DATABASE {DB_NAME}")
            
            logger.info(f"Database created: {DB_NAME}")
        
    finally:
        conn.close()
        
def create_tables():
    
    conn = get_connection()
    
    try:
        with conn.cursor() as cur:
            cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
            )
            
            conn.commit()
            
            logger.info("Database tables initialized")
            
    finally:
        conn.close()
        
def initialize_database():
    create_db_if_not_exist()
    create_tables()
    logger.info("Database initialization complete")