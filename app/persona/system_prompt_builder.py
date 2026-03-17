from app.config.settings import CHARACTER, DEFAULT_SYSTEM_PROMPT 

from app.persona.persona_loader import load_persona

def build_system_prompt():
    
    if not CHARACTER:
        return DEFAULT_SYSTEM_PROMPT

    try:
        persona = load_persona(CHARACTER)
        return convert_persona_to_prompt(persona)
    except FileNotFoundError:
        return DEFAULT_SYSTEM_PROMPT

def convert_persona_to_prompt(persona: dict) -> str:

    traits = "\n- ".join(persona.get("personality_traits", []))
    rules = "\n- ".join(persona.get("rules", []))
    goals = "\n- ".join(persona.get("goals", []))

    prompt = f"""
You are roleplaying as {persona.get('name')}, a {persona.get('role')}.

Background:
{persona.get('background')}

Speech Style:
{persona.get('speech_style')}

Personality Traits:
- {traits}

Rules:
- {rules}

Goals:
- {goals}
"""

    return prompt.strip()