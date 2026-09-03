import re
import json


def parse_segments(text):
    """
    Splits a response string containing inline [emotion] tags into
    a list of (emotion, text) tuples for OLED and facial expression rendering.

    Example input:
      "[worried]Hmm, I'm not sure... [focused]Let me think... [happy]Actually yes!"

    Example output:
      [("worried", "Hmm, I'm not sure..."),
       ("focused", "Let me think..."),
       ("happy", "Actually yes!")]
    """
    matches = re.findall(r'\[([a-z]+)\]([^\[]*)', text)
    segments = []

    for emotion, chunk in matches:
        chunk = chunk.strip()
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
