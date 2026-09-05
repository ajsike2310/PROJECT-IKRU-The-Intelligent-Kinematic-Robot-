import re
import json


# OLED facial emotion names (distinct from TTS voice tags like [chuckle], [laugh], [sigh])
OLED_EMOTIONS = [
    "normal", "happy", "glee", "sad", "worried", "focused", "annoyed",
    "surprised", "skeptic", "frustrated", "unimpressed", "sleepy",
    "suspicious", "squint", "angry", "furious", "scared", "awe"
]
EMOTION_REGEX = re.compile(r'\[(' + '|'.join(OLED_EMOTIONS) + r')\]', re.IGNORECASE)


def parse_segments(text):
    """
    Splits a response string containing inline OLED [emotion] tags into
    a list of (emotion, text) tuples for facial expression rendering.
    Preserves Chatterbox paralinguistic voice tags ([chuckle], [laugh], [sigh],
    [gasp], [clear throat]) inside the text content for the speech synthesizer.

    Example input:
      "[happy]Hi there [chuckle]! [focused]Let me compute that... [glee]Done!"

    Example output:
      [("happy", "Hi there [chuckle]!"),
       ("focused", "Let me compute that..."),
       ("glee", "Done!")]
    """
    if not text or not text.strip():
        return []

    parts = EMOTION_REGEX.split(text)
    segments = []

    # Handle text preceding the first emotion tag
    if parts[0].strip():
        segments.append(("normal", parts[0].strip()))

    for i in range(1, len(parts), 2):
        emotion = parts[i].lower()
        chunk = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if chunk:
            segments.append((emotion, chunk))

    return segments


def parse_llm_json(raw_text):
    """
    Safely parses JSON responses from the local LLM.
    Handles tool calls and response text with automatic fallback for malformed JSON.
    """
    raw_text = raw_text.strip()

    # Strip markdown code blocks if the model wrapped output
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
        tools = data.get("tools", [])

        # Backwards compatibility if model used single 'tool' string
        tool = data.get("tool", None)
        if tool is not None and isinstance(tool, str):
            tools.append({"action": tool, "duration": 0})

        response_text = data.get("response", "").strip()
        return tools, response_text

    except json.JSONDecodeError:
        return [], raw_text
