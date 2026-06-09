from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

import time
import uuid

class ChatRequest(BaseModel):
    session_id: str
    messages: str
    
class ChatResponse(BaseModel):
    response: str
    request_id: str
    latency: float
    
def create_api(application):
    
    app = FastAPI()
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        
        request_id = uuid.uuid4().hex[:8]
        
        start = time.time()
        
        response = await application.chat_service.chat(
            user_input=req.messages,
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

            async for chunk in application.chat_service.chat_stream(
                user_input=req.messages,
                session_id=req.session_id
            ):
                yield chunk

        return StreamingResponse(
            generator(),
            media_type="text/plain"
        )

    return app