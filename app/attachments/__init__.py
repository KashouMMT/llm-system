"""
Attachments: reading back what the user uploaded.

Deliberately empty of imports. app/llm/system_prompt.py imports
app.attachments.prompts, and a package __init__ that pulled in tools.py
would drag repositories and pypdf into the prompt loader's import graph.
Import make_attachment_tools from app.attachments.tools directly.
"""
