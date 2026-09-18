import speech_recognition as sr

class MicController:
    """
    Handles microphone initialization, ambient noise calibration,
    and speech-to-text processing via Google Web Speech API.
    """
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.3  # Extremely snappy end-of-speech detection
        self.recognizer.non_speaking_duration = 0.2
        self.mic = sr.Microphone()
        
        print("[Audio] Initializing Microphone...")
        with self.mic as source:
            print("[Audio] Calibrating ambient noise... please wait 2 seconds.")
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
        print("[Audio] Microphone ready.")

    def listen(self) -> str:
        """
        Listens to the microphone until silence is detected and returns the recognized text.
        Returns an empty string if the speech couldn't be recognized.
        """
        print("\n[Mic] Listening... (Say 'exit' to quit)")
        try:
            with self.mic as source:
                audio_data = self.recognizer.listen(source, timeout=None, phrase_time_limit=None)
            print("  [Processing audio...]")
            text = self.recognizer.recognize_google(audio_data)
            return text
        except sr.UnknownValueError:
            print("  [Could not understand audio. Try again]")
            return ""
        except sr.RequestError as e:
            print(f"  [STT Error: {e}]")
            return ""

    def start_background_listening(self, callback):
        """
        Starts listening in a background thread.
        `callback` should be a function that accepts `(recognizer, audio)`.
        Returns a stop function that can be called to terminate the background thread.
        """
        # listen_in_background uses the existing recognizer and mic to spawn a daemon thread.
        return self.recognizer.listen_in_background(self.mic, callback)
