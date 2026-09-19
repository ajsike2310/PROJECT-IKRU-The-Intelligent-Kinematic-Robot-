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
            "Focus on people, clothing colors, objects, and setting. Be factual and concise. "
            "There is a 5x5 white grid drawn over the image. Use this grid to estimate how close "
            "the main object/person is. If it takes up 1-2 squares, it is far. If it takes up 4-9 squares, "
            "it is medium distance. If it takes up 12+ squares, it is extremely close. Mention the estimated distance."
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
