# llm-system
A Chat LLM System With LangChain Libraray And Ollama.

```
ai-llm-project/
│
├── api/                             # API endpoints
│   └── fastapi.py                   # Fastapi main entry point
├── app/                             # Main LLM Related Files
│   ├── main.py                      # Direct Conversation with LLM on console output.
│   ├── config/                      # Configuration Folder
│   │   └── settings.py              # Configuration file for LLM 
│   ├── data/                        # Character Behavior and Personality Data Folder
│   │   └── ethan_salesman.json      # Example Character
│   ├── llm/                         # LLM Folder
│   │   ├── chain_factory.py         # Lang Chain orchestrator
│   │   ├── llm_factory.py           # Ollama Client
│   │   └── prompt_factory.py        # Prompt
│   ├── logs/                        # LLM logs
│   ├── memory/                      # Memory Folder
│   │   ├── memory_router.py         # LLM Memory Orchestrator
│   │   ├── short_term_memory.py     # Short Term Memory Access
│   │   ├── summary_memory.py        # Conversation Summarization
│   │   └── vector_memory.py         # Vector DB (RAG) // To implement in future
│   ├── persona/                     # Character Prompt function related folder
│   │   ├── persona_loader.py        # Load Character behavior and Personality from data folder
|   |   └── system_prompt_builder.py # Convert and build System prompt from persona_loader
│   ├── services/                    # Services folder
│   │   └── chat_service.py          # Main Chat Service
│   └── utils/                       # Utility Folder
│       └── logger.py                # Logging
├── ui/                              # React UI // To implement in future. Currently Empty shell
├── LICENSE
├── README.md
└── requirements.txt
```