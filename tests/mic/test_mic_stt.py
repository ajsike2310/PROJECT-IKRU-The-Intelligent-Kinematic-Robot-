import speech_recognition as sr

def test_microphone_and_stt():
    """
    Trial code to listen to the laptop microphone and convert speech to text.
    Requires: pip install SpeechRecognition pyaudio
    """
    recognizer = sr.Recognizer()
    
    print("=== IKRU STT Trial ===")
    print("Listing available microphones...")
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"[{index}] {name}")

    print("\nInitializing microphone (using default)...")
    try:
        with sr.Microphone() as source:
            print("Calibrating ambient noise... please stay quiet for 2 seconds.")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            print("🎤 Listening! Please speak now...")
            
            # Listen to the microphone (ends automatically when you stop speaking)
            audio_data = recognizer.listen(source, timeout=None, phrase_time_limit=None)
            
            print("⏳ Processing audio...")
            
            # Using Google Web Speech API for this trial (easy to set up without heavy local models)
            # If you want offline STT (like Whisper), you can install `openai-whisper` 
            # and change this to: text = recognizer.recognize_whisper(audio_data, model="base")
            try:
                text = recognizer.recognize_google(audio_data)
                print(f"\n✅ Recognized Text: '{text}'")
            except sr.UnknownValueError:
                print("❌ The model could not understand the audio (UnknownValueError).")
            except sr.RequestError as e:
                print(f"❌ Could not request results from STT service; {e}")
                
    except OSError as e:
        print(f"\n❌ Error accessing microphone: {e}")
        print("Note: PyAudio might be missing or unsupported. Try running:")
        print("pip install pyaudio")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

if __name__ == "__main__":
    test_microphone_and_stt()
