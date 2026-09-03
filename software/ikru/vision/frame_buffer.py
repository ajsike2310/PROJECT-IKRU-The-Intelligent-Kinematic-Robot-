import threading
import cv2


class FrameBuffer:
    """
    Thread-safe single latest-frame buffer with zero queue buildup.
    """

    def __init__(self, vlm_jpeg_quality=85):
        self._frame = None
        self._lock = threading.Lock()
        self.vlm_jpeg_quality = vlm_jpeg_quality

    def set_frame(self, frame):
        """Updates the buffer with the newest frame."""
        with self._lock:
            self._frame = frame

    def get_frame(self):
        """Returns a copy of the latest raw frame as a numpy array, or None."""
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def get_jpeg_bytes(self, quality=None):
        """Returns the latest frame encoded as JPEG bytes for VLM queries."""
        frame = self.get_frame()
        if frame is None:
            return None

        if quality is None:
            quality = self.vlm_jpeg_quality

        success, encoded = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        if not success:
            return None
        return bytes(encoded)

    def has_frame(self):
        """Returns True if at least one valid frame has been received."""
        with self._lock:
            return self._frame is not None
