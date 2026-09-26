import json
import threading
import ollama
from .prompts import SYSTEM_PROMPT
from .parser import parse_segments, parse_llm_json


class ChatEngine:
    """
    Main conversational engine interfacing with local Ollama LLM (Qwen 2.5 3B).
    Integrates persistent memory via MemoryManager (SQLite + Qdrant).
    """

    def __init__(self, model="qwen2.5:3b", memory=None, keep_alive="30m"):
        self.model = model
        self.memory = memory
        self.keep_alive = keep_alive
        # Guards self.messages — the autonomous brain appends from its own thread
        self._messages_lock = threading.Lock()
        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }
        ]

    def warm_up(self):
        """Loads the model into memory so the first reply doesn't pay the load time."""
        try:
            ollama.generate(model=self.model, prompt="", keep_alive=self.keep_alive)
            print(f"[ChatEngine] {self.model} loaded and kept warm ({self.keep_alive}).")
        except Exception as e:
            print(f"[ChatEngine] Warm-up skipped ({e}).")

    def clear_history(self):
        """Resets conversational memory back to initial system prompt."""
        with self._messages_lock:
            self.messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                }
            ]

    def note_autonomous_utterance(self, response_text, tools=None):
        """
        Adds something Ikru said on its own (autonomous thought / question) to the
        conversation window, so a user replying to it gets a reply in context.
        """
        with self._messages_lock:
            if len(self.messages) > 11:
                self.messages = [self.messages[0]] + self.messages[-10:]
            self.messages.append({
                "role": "assistant",
                "content": json.dumps({"tools": tools or [], "response": response_text}),
            })

    def ask(self, user_input, visual_context=None, sensor_context=None, action_context=None):
        """
        Sends a user message to Ollama with optional injected visual context,
        sensor context (e.g. proximity), and recalled long-term memory.
        Returns:
            tools (list): list of tool actions dicts
            response_text (str): raw formatted response with inline emotion tags
            segments (list): list of (emotion, text) tuples
        """
        # Maintain a sliding window: preserve system prompt + up to 10 latest messages
        with self._messages_lock:
            if len(self.messages) > 11:
                self.messages = [self.messages[0]] + self.messages[-10:]

        # Build augmented input with memory context and visual observations
        augmented_parts = []

        # 1. Inject recalled long-term memories from Qdrant + SQLite facts
        if self.memory:
            try:
                memory_context = self.memory.build_memory_context(user_input)
                if memory_context:
                    augmented_parts.append(memory_context)
            except Exception as e:
                print(f"[ChatEngine] Memory recall warning: {e}")

        # 2. Inject visual context from camera
        if visual_context:
            augmented_parts.append(f"[Camera Visual Observation: {visual_context.strip()}]")

        # 3. Inject raw sensor context (proximity, etc.) — passed through as-is
        if sensor_context:
            augmented_parts.append(sensor_context.strip())

        # 4. Inject the action the tool router already decided on (so words match the body)
        if action_context:
            augmented_parts.append(action_context.strip())

        # 5. Append the actual user message
        augmented_parts.append(f"User: {user_input}" if augmented_parts else user_input)

        augmented_input = "\n".join(augmented_parts)

        # Record user message to persistent memory (non-blocking)
        if self.memory:
            try:
                self.memory.record_user_message(user_input, visual_context=visual_context)
            except Exception as e:
                print(f"[ChatEngine] Memory record warning: {e}")

        with self._messages_lock:
            self.messages.append({
                "role": "user",
                "content": augmented_input
            })
            history = list(self.messages)

        try:
            # Query local Ollama LLM
            response = ollama.chat(
                model=self.model,
                messages=history,
                format="json",
                keep_alive=self.keep_alive,
            )
            assistant_raw = response["message"]["content"].strip()
            tools, response_text = parse_llm_json(assistant_raw)
        except Exception as e:
            print(f"[ChatEngine] Warning: Ollama chat error ({e}), attempting plain text fallback...")
            try:
                fallback_res = ollama.chat(
                    model=self.model,
                    messages=history,
                    keep_alive=self.keep_alive,
                )
                assistant_raw = fallback_res["message"]["content"].strip()
                tools, response_text = parse_llm_json(assistant_raw)
            except Exception as ex2:
                print(f"[ChatEngine] LLM query failed completely: {ex2}")
                tools, response_text = [], f"[sad]I am having a moment of trouble thinking right now. [sigh] Let's try again in a second!"

        segments = parse_segments(response_text)
        if not segments:
            segments = [("normal", response_text)]

        # Append assistant response to sliding window history
        with self._messages_lock:
            self.messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "tools": tools,
                    "response": response_text
                })
            })

        # Record assistant response to persistent memory (non-blocking)
        if self.memory:
            try:
                self.memory.record_assistant_message(response_text, tools_used=tools)
            except Exception as e:
                print(f"[ChatEngine] Memory record warning: {e}")

        return tools, response_text, segments


