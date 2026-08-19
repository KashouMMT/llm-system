from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

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
    
    @app.get("/history/{session_id}")
    async def get_history(session_id: str):
        
        messages = application.message_repository.get_messages(
            session_id
        )
        
        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3]
            }
            for row in messages
        ]

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