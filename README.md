# llm-system
A Chat LLM System With LangChain Libraray And Ollama.

## Folder Structure

``` 
llm-system/
├── app/                                          # Main LLM Related Files
│   ├── main.py                                   # Main entry point (CLI or --api)
│   ├── agent/                                    # LangGraph orchestrator
│   │   ├── nodes/
│   │   │   ├── prepare_context_node.py           # Builds prepared_context once per request
│   │   │   ├── agent_node.py                     # LLM decision node (binds tools, invokes model)
│   │   │   └── compact_checkpoint_state_node.py  # Bounds checkpoint history after a final answer
│   │   ├── tools/                                # Tools the agent may choose to call
│   │   │   └── time_tool.py
│   │   ├── context/
│   │   │   ├── conversation_context_builder.py   # Builds context supplied to the agent (active)
│   │   │   └── context_builder.py                # Earlier version, appears superseded/unused
│   │   ├── checkpointer.py                       # Creates the AsyncPostgresSaver checkpoint context
│   │   ├── graph.py                              # Defines and compiles the LangGraph
│   │   └── state.py                              # Defines LangGraph state (AgentState)
│   ├── config/
│   │   └── settings.py                           # Load env values, other constant variables
│   ├── database/
│   │   ├── connection.py                         # Create connection with database
│   │   └── init_db.py                            # Initialize database and tables if not exist
│   ├── llm/                                      # LLM Folder. In future, will support LLM switching.
│   │   ├── llm_factory.py                        # Currently supports Ollama client
│   │   └── prompt_factory.py                     # Prompt loading; in future, system prompt switching from user side
│   ├── logs/                                     # Logs
│   ├── memory/
│   │   ├── memory_router.py                      # Not sure of its purpose currently. Perhaps should be deleted in future.
│   │   ├── summary_memory.py                     # Summarization logic. Not integrated with current LangGraph framework.
│   │   └── vector_memory.py                      # RAG logic. Not integrated with current LangGraph framework.
│   ├── persona/
│   │   └── load_prompt.py                        # Load prompt from prompts folder below
│   ├── prompts/                                  # Character behavior and personality for LLM. Basically system prompts.
│   ├── repositories/                             # Functions for executing SQL against tables.
│   │   ├── conversation_repository.py            # Conversations (One)->(Many) Messages
│   │   ├── message_repository.py                 
│   │   └── summary_repository.py                 # Table for summarization logic.
│   ├── runtime/
│   │   ├── application.py                        # Initializes entire app. Composition root and lifecycle owner.
│   │   ├── cli.py                                # CLI interface for app.
│   │   └── server.py                             # FastAPI REST API for app.
│   ├── services/
│   │   └── chat_service.py                       # Main chat service
│   └── utils/
│       └── logger.py                             # Logging
├── ui/                                           # React UI. Communicates with FastAPI. Empty shell, not yet implemented.
├── LICENSE
├── README.md
└── requirements.txt
```