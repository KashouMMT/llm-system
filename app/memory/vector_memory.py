from app.utils.logger import logger

# Currently a placeholder for RAG

class VectorMemory:
    def __init__(self, vector_db: None):
        self.vector_db = vector_db
        
    def store_memory(self, text):
        if not self.vector_db:
            return

        logger.debug("Storing vector memory")
        
        self.vector_db.add_texts([text])
        
    def retrieve(self, query):
        if not self.vector_db:
            return []
        
        logger.debug("Retrieving vectory memory")
        
        return self.vector_db.similarity_search(query)