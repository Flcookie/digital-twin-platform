import json
from pathlib import Path


def load_json(path: str):
    """Load a JSON file from the current project directory."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_topic(context: str, source_id: str, target_id: str) -> str:
    """
    Build an MQTT topic.
    Uses a simple 3-segment format compatible with this dashboard.
    """
    return f"{context}/{source_id}/{target_id}"


def parse_topic(topic: str):
    """
    Parse topic into (context, source_id, target_id).
    If segments are missing, fill with empty strings.
    """
    parts = str(topic).split("/")
    parts += [""] * (3 - len(parts))
    return parts[0], parts[1], parts[2]


def deserialize_object(payload: str):
    """
    Try to parse payload as JSON object.
    If parsing fails, return raw payload string.
    """
    try:
        return json.loads(payload)
    except Exception:
        return payload
