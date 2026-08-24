import ollama


class VLMClient:
    """
    On-demand Vision-Language Model interface for querying camera snapshots via Ollama.
    """

    def __init__(self, model="qwen3-vl:4b"):
        self.model = model

    def describe_scene(self, jpeg_bytes, custom_prompt=None):
        """
        Sends a single un-annotated JPEG snapshot to the local VLM.
        Returns a concise 1-2 sentence description, or None if unavailable.
        """
        if not jpeg_bytes:
            return None

        prompt = custom_prompt or (
            "Describe what you see in the image in 1-2 short sentences. "
            "Focus on people, clothing colors, objects, and setting. Be factual and concise."
        )

        try:
            res = ollama.generate(
                model=self.model,
                prompt=prompt,
                images=[jpeg_bytes]
            )
            return res.response.strip()
        except Exception as e:
            print(f"[VLM] Query failed: {e}")
            return None
