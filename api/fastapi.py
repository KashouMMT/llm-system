from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from app.persona.load_prompt import load_prompt
from app.llm.llm_factory import LLMFactory
from app.llm.prompt_factory import PromptFactory
from app.llm.chain_factory import ChainFactory
from app.memory.memory_router import MemoryRouter
from app.services.chat_service import ChatService

import time
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Initialize once (important) ---
system_prompt = load_prompt()
llm = LLMFactory.create()
prompt = PromptFactory.create(system_prompt)
memory = MemoryRouter(llm)
chain = ChainFactory.create(prompt, llm, memory)
chat_service = ChatService(chain, memory, system_prompt)

# --- Request Schema ---
class ChatRequest(BaseModel):
    session_id: str
    message: str

# --- Request Schema ---
class ChatResponse(BaseModel):
    response: str
    request_id: str
    latency: float

# --- Endpoint ---
@app.post("/chat",response_model=ChatResponse)
async def chat(req: ChatRequest):
    request_id = uuid.uuid4().hex[:8]
    start = time.time()
    
    response = await chat_service.chat(
        user_input=req.message,
        session_id=req.session_id
    )
    
    latency = time.time() - start
    
    return ChatResponse(
        response=response,
        request_id=request_id,
        latency=latency
    )
    
@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    
    async def generator():
        async for chunk in chat_service.chat_stream(
            user_input=req.message,
            session_id=req.session_id
        ):
            yield chunk
    
    return StreamingResponse(generator(), media_type="text/plain")