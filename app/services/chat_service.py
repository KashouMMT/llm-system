import time
import uuid

from langchain_core.messages import get_buffer_string
from app.utils.logger import logger

class ChatService:
    def __init__(self,chain,memory,system_prompt):
        self.chain = chain
        self.memory = memory
        self.system_prompt = system_prompt
        logger.info("ChatService initialized")
        
    async def chat(self, user_input: str, session_id: str = "default") -> str:
        request_id = uuid.uuid4().hex[:8]
        
        logger.info(f"request={request_id} session={session_id} user_input={user_input}")
        
        start = time.time()
        
        response = self.chain.ainvoke(
            {"user_input": user_input},
            config={"configurable": {"session_id": session_id}},
        )
        
        latency = time.time() - start
        
        logger.info(f"request={request_id} session={session_id} latency={latency:.2f}s")
        
        # Access memory for debugging
        history = self.memory.get_session_history(session_id)
        history_text = get_buffer_string(history.messages)
        
        logger.debug(
        f"""
REQUEST DEBUG
session={session_id}
request={request_id}

SYSTEM PROMPT:
{self.system_prompt}

USER INPUT:
{user_input}

HISTORY:
{history_text}

LLM RESPONSE:
{response.content}
"""
)
        
        return response.content
    
    async def chat_stream(self, user_input: str, session_id: str = "default"):

        request_id = uuid.uuid4().hex[:8]
        logger.info(f"stream_request={request_id} session={session_id}")

        start = time.time()
        
        response_buffer = []
        
        async for chunk in self.chain.astream(
            {"user_input": user_input},
            config={"configurable": {"session_id": session_id}},
        ):
            if chunk.content:
                response_buffer.append(chunk.content)
                yield chunk.content
        
        latency = time.time() - start
        response_text = "".join(response_buffer)
        
        logger.info(f"stream_request={request_id} latency={latency:.2f}s")
        
        # Access memory for debugging
        history = self.memory.get_session_history(session_id)
        history_text = get_buffer_string(history.messages)
        
        logger.debug(
        f"""
REQUEST DEBUG
session={session_id}
request={request_id}

SYSTEM PROMPT:
{self.system_prompt}

USER INPUT:
{user_input}

HISTORY:
{history_text}

LLM RESPONSE:
{response_text}
"""
)