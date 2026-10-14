import re
import json

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

    def list_objects(self, jpeg_bytes):
        """
        Asks the VLM for a one-sentence scene summary plus short object names,
        used by the autonomous world model to remember landmarks on the desk.
        Returns {"scene": str, "objects": [str, ...]} or None if unavailable.
        """
        if not jpeg_bytes:
            return None

        prompt = (
            "You are the eyes of a small desk robot. Ignore any grid lines drawn over the image. "
            'Reply ONLY with JSON: {"scene": "<one short sentence>", '
            '"objects": ["<up to 5 main objects, 1-2 words each>"]}'
        )

        try:
            res = ollama.generate(
                model=self.model,
                prompt=prompt,
                images=[jpeg_bytes],
                format="json",
            )
            raw = res.response.strip()
        except Exception as e:
            print(f"[VLM] Object query failed: {e}")
            return None

        data = None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = None
        if not isinstance(data, dict):
            return {"scene": raw[:200], "objects": []} if raw else None

        objects = data.get("objects") or []
        if isinstance(objects, str):
            objects = [o.strip() for o in objects.split(",")]
        objects = [str(o).strip() for o in objects if str(o).strip()][:5]
        return {"scene": str(data.get("scene", "")).strip(), "objects": objects}

    def classify_target(self, jpeg_bytes, target):
        """
        Object search: is the nearest object in front of the robot the `target`?
        Returns {"what": str, "match": bool, "confidence": float} or None.
        """
        if not jpeg_bytes:
            return None

        prompt = (
            f'You are the eyes of a small desk robot that is searching for: "{target}". '
            "The robot has stopped right in front of an obstacle. Ignore any grid lines drawn "
            "over the image. Look at the object nearest the camera (usually centre / bottom). "
            'Reply ONLY with JSON: {"what": "<1-3 word name of that nearest object>", '
            f'"match": <true if it is a {target}, else false>, '
            f'"confidence": <0.0-1.0 how sure you are that it is a {target}>}}'
        )

        try:
            res = ollama.generate(model=self.model, prompt=prompt, images=[jpeg_bytes], format="json")
            raw = res.response.strip()
        except Exception as e:
            print(f"[VLM] Target classification failed: {e}")
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            try:
                data = json.loads(match.group(0)) if match else None
            except json.JSONDecodeError:
                data = None
        if not isinstance(data, dict):
            return None

        is_match = data.get("match", False)
        if isinstance(is_match, str):
            is_match = is_match.strip().lower() in ("true", "yes", "1")
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 1.0 if is_match else 0.0))))
        except (TypeError, ValueError):
            confidence = 1.0 if is_match else 0.0
        return {"what": str(data.get("what", "")).strip(), "match": bool(is_match), "confidence": confidence}
