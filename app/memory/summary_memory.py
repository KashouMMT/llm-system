from langchain_core.messages import HumanMessage

from app.utils.logger import logger

class SummaryMemory:
    
    def __init__(self, llm, max_tokens: int = 2000):
        self.llm = llm
        self.max_tokens = max_tokens
        
    def estimate_tokens(self, messages):
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // 4
    
    def summarize_messages(self, messages):
        text = "\n".join([f"{m.type}: {m.content}" for m in messages])
        prompt = f"""
Summarize the following conversation while preserving important context.

Conversation:
{text}

Summary:
"""
        response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content

    def compress_if_needed(self, history):
        messages = history.messages
        
        token_count = self.estimate_tokens(messages)
        if token_count <= self.max_tokens:
            return history
        
        logger.debug("SummaryMemory Triggered")
        
        midpoint = len(messages) // 2
        old_messages = messages[:midpoint]
        recent_messages = messages[midpoint:]
        
        summary = self.summarize_messages(old_messages)
        
        new_messages = [
            HumanMessage(content=f"Conversation summary: {summary}")
        ] + recent_messages
        
        history.messages.clear()
        for msg in new_messages:
            history.add_message(msg)
        
        logger.debug("Conversation summarized")
        
        return history