import json
import ollama
from .prompts import SYSTEM_PROMPT
from .parser import parse_segments, parse_llm_json


class ChatEngine:
    """
    Main conversational engine interfacing with local Ollama LLM (Qwen 2.5 3B).
    """

    def __init__(self, model="qwen2.5:3b"):
        self.model = model
        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

    def ask(self, user_input, visual_context=None):
        """
        Sends a user message to Ollama with optional injected visual context.
        Returns:
            tools (list): list of tool actions dicts
            response_text (str): raw formatted response with inline emotion tags
            segments (list): list of (emotion, text) tuples
        """
        # Prepare content with optional visual context
        if visual_context:
            augmented_input = (
                f"[Camera Visual Observation: {visual_context.strip()}]\n"
                f"User: {user_input}"
            )
        else:
            augmented_input = user_input

        self.messages.append({
            "role": "user",
            "content": augmented_input
        })

        # Query local Ollama LLM
        response = ollama.chat(
            model=self.model,
            messages=self.messages,
            format="json"
        )

        assistant_raw = response["message"]["content"].strip()
        tools, response_text = parse_llm_json(assistant_raw)
        segments = parse_segments(response_text)

        if not segments:
            segments = [("normal", response_text)]

        # Append assistant response to history
        self.messages.append({
            "role": "assistant",
            "content": json.dumps({
                "tools": tools,
                "response": response_text
            })
        })

        return tools, response_text, segments
