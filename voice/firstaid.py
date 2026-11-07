"""First aid guidance module for search and rescue operations.

Steps are loaded from voice/firstaid.json. Each step carries a verified source URL.
The system provides guidance for humans, never medical diagnosis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_FIRSTAID_PATH = Path(__file__).resolve().parent / "firstaid.json"


def load_firstaid_data(path: Path | str | None = None) -> dict[str, Any]:
    """Load the raw first aid dataset from JSON."""
    file_path = Path(path) if path is not None else DEFAULT_FIRSTAID_PATH
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_steps(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Return the list of validated first aid steps."""
    data = load_firstaid_data(path)
    steps = data.get("steps", [])
    return steps


def get_step(action_or_id: str, path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve a step by step id (e.g. 'step_1') or action (e.g. 'check_breathing')."""
    steps = get_steps(path)
    for step in steps:
        if step.get("id") == action_or_id or step.get("action") == action_or_id:
            return step
    return None


def format_guidance(step: dict[str, Any]) -> str:
    """Format a step into guidance for a human to follow aloud."""
    title = step.get("title", "First Aid Step")
    guidance = step.get("guidance", "")
    return f"{title}: {guidance}"


def create_say_message(
    action_or_id: str,
    to: str = "casualty",
    lang: str = "auto",
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Create a CONTRACT-compliant 'say' message for a given first aid step."""
    step = get_step(action_or_id, path)
    if step is None:
        raise ValueError(f"Unknown first aid step: {action_or_id}")
    text = format_guidance(step)
    return {
        "to": to,
        "intent": "first_aid",
        "text": text,
        "lang": lang,
    }
