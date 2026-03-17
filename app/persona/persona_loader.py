import json
from pathlib import Path

def load_persona(persona_name: str):
    base_path = Path(__file__).resolve().parent.parent
    persona_path = base_path / "data" / f"{persona_name}.json"
    
    with open(persona_path, "r", encoding="utf-8") as f:
        return json.load(f)