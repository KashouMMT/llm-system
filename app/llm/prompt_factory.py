from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

class PromptFactory:
    
    @staticmethod
    def create(system_prompt: str):
        
        return ChatPromptTemplate.from_messages(
            [
                ("system",system_prompt),
                MessagesPlaceholder(variable_name="history"),
                ("human","{user_input}")
            ]
        )