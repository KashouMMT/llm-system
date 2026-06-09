import psycopg

from app.config.settings import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
)

from app.utils.logger import logger

def get_connection():
    try:
        conn = psycopg.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        logger.info("PostgreSQL connected")
        
        return conn

    except Exception as e:
        logger.exception("Failed to connect PostgreSQL")
        raise e