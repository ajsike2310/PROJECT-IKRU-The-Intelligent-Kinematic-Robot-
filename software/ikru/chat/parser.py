import re
import json


# OLED facial emotion names (distinct from TTS voice tags like [chuckle], [laugh], [sigh])
OLED_EMOTIONS = [
    "normal", "happy", "glee", "sad", "worried", "focused", "annoyed",
    "surprised", "skeptic", "frustrated", "unimpressed", "sleepy",
    "suspicious", "squint", "angry", "furious", "scared", "awe"
]
EMOTION_REGEX = re.compile(r'\[(' + '|'.join(OLED_EMOTIONS) + r')\]', re.IGNORECASE)


VOCAL_TO_OLED = [
    (re.compile(r'\[(?:laugh|laughter|cackle|haha+)\]', re.IGNORECASE), 'glee'),
    (re.compile(r'\[(?:giggle|chuckle|snicker)\]', re.IGNORECASE), 'happy'),
    (re.compile(r'\[(?:cry|crying|sob|weep)\]', re.IGNORECASE), 'sad'),
    (re.compile(r'\[(?:sigh|sighs)\]', re.IGNORECASE), 'worried'),
    (re.compile(r'\[(?:gasp|gasps|shocked)\]', re.IGNORECASE), 'surprised'),
    (re.compile(r'\[(?:groan|groans)\]', re.IGNORECASE), 'frustrated'),
    (re.compile(r'\[(?:clear[\s_]?throat|clear)\]', re.IGNORECASE), 'focused'),
    (re.compile(r'\[(?:whisper)\]', re.IGNORECASE), 'suspicious'),
    (re.compile(r'\[(?:cough)\]', re.IGNORECASE), 'annoyed'),
]


def parse_segments(text):
    """
    Splits a response string containing inline OLED [emotion] tags into
    a list of (emotion, text) tuples for facial expression rendering.
    Preserves Chatterbox paralinguistic voice tags ([giggle], [laughter], [sigh],
    [gasp], [clear_throat], [cry]) inside the text content for the speech synthesizer.

    If no explicit OLED tag was provided, automatically infers the facial expression
    from vocal sounds (e.g. [laugh] -> glee, [clear_throat] -> focused) or sentiment,
    ensuring the robot face is always expressive and emotions are never skipped.
    """
    if not text or not text.strip():
        return []

    parts = EMOTION_REGEX.split(text)
    segments = []

    # Handle text preceding the first explicit OLED emotion tag
    if parts[0].strip():
        segments.append(("normal", parts[0].strip()))

    for i in range(1, len(parts), 2):
        emotion = parts[i].lower()
        chunk = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if chunk:
            segments.append((emotion, chunk))

    if not segments and text.strip():
        segments.append(("normal", text.strip()))

    # Refine segments: if emotion is 'normal', infer from vocal tags or sentiment
    refined = []
    for emotion, chunk in segments:
        if emotion == "normal":
            for pattern, inferred_emo in VOCAL_TO_OLED:
                if pattern.search(chunk):
                    emotion = inferred_emo
                    break

            if emotion == "normal":
                lower = chunk.lower()
                if any(w in lower for w in ["haha", "funny", "hilarious", "glad", "great", "awesome", "welcome", "hello", "hi"]):
                    emotion = "happy"
                elif any(w in lower for w in ["sorry", "unfortunately", "sad", "hurts", "bad", "crying"]):
                    emotion = "sad"
                elif any(w in lower for w in ["looking", "scanning", "checking", "see", "ready", "detect", "computing"]):
                    emotion = "focused"
                elif any(w in lower for w in ["angry", "mad", "grr", "furious"]):
                    emotion = "angry"
                else:
                    emotion = "happy"

        refined.append((emotion, chunk))

    return refined


def parse_llm_json(raw_text):
    """
    Safely parses JSON responses from the local LLM.
    Handles tool calls and response text with automatic fallback for malformed JSON.
    Also recovers top-level 'emotion' fields if the LLM placed the tag outside response.
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

        # If LLM put 'emotion' as a separate JSON field, inject it into response_text
        outer_emotion = data.get("emotion", "")
        if outer_emotion and isinstance(outer_emotion, str) and not response_text.startswith("["):
            response_text = f"[{outer_emotion.strip().lower()}] {response_text}"

        return tools, response_text

    except json.JSONDecodeError:
        return [], raw_text
