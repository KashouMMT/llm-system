from langchain_core.runnables.history import RunnableWithMessageHistory

from app.utils.logger import logger

class ChainFactory:
    
    @staticmethod
    def create(prompt, llm, memory_manager):
        logger.info("Building chat chain")
        
        chain = prompt | llm
        
        chain_with_memory = RunnableWithMessageHistory(
            chain,
            memory_manager.get_session_history,
            input_messages_key="user_input",
            history_messages_key="history",
        )
        
        logger.info("Chat chain ready")

        return chain_with_memory