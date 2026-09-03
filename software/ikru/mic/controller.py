import speech_recognition as sr

class MicController:
    """
    Handles microphone initialization, ambient noise calibration,
    and speech-to-text processing via Google Web Speech API.
    """
    def __init__(self):
        self.recognizer = sr.Recognizer()
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
        print("\n🎤 Listening... (Say 'exit' to quit)")
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
