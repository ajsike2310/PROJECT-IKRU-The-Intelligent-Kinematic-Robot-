# IKRU R2-D2 Sonic Emotion & Sentence Prosody System

The **IKRU Sonic Emotion System** gives IKRU an authentic, expressive **Astromech / R2-D2 droid vocal personality**. Instead of speaking text transcripts, IKRU replicates human and robot sentences into natural **droid speech prosody**—using continuous glissando sweeps (chirps), rapid warbles/trills, conversational staccato syllables, and emotional whistling flourishes.

---

## 1. System Architecture & Sentence Prosody

```
               Natural Language Sentence
          ("I found your mug on the desk!")
                         │
                         ▼
        ┌──────────────────────────────────┐
        │     Sentence Prosody Analyzer    │
        │   - Sentiment & Emotion Detection│
        │   - Punctuation & Contour (? / !)│
        │   - Syllable Cadence & Length    │
        └────────────────┬─────────────────┘
                         │
                         ▼
        ┌──────────────────────────────────┐
        │  R2-D2 Droid Synthesis Engine    │
        │  - Continuous Glissando Sweeps   │
        │  - Multi-Pitch Syllable Chirps   │
        │  - Soaring Whistles & Trills     │
        └────────────────┬─────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
    Local PC Audio               ESP32 Speaker
 (Pure Python 22kHz WAV)      (Non-blocking Hardware PWM)
```

---

## 2. Sentence-to-Droid Translation Examples

| Input Sentence | Detected Mood & Contour | R2-D2 Droid Vocalization Behavior |
| :--- | :--- | :--- |
| `"I found your mug on the desk!"` | **HAPPY / EXCLAMATION** | Rising syllable chirps ($1300\text{Hz} \rightarrow 2800\text{Hz}$) ending in an ecstatic high whistle ($3200\text{Hz}$). |
| `"What are you doing over there?"` | **QUESTION / CONFUSED** | Conversational mid-pitch chatter ending in a distinctive upward **question-mark hook** ($950\text{Hz} \rightarrow 2800\text{Hz}$, `boop-WEEP?`). |
| `"Oh no, I am so sorry I failed..."` | **SAD / APOLOGY** | Descending sorrowful syllable slides trailing down into a low droop ($1900\text{Hz} \rightarrow 500\text{Hz}$, `whooo-oo-op...`). |
| `"Warning! Obstacle detected ahead!"` | **WARNING / ALERT** | Rapid alternating siren chirps ($2200\text{Hz} \leftrightarrow 3400\text{Hz}$ in urgent bursts). |
| `"Good night, I am going to sleep."` | **SLEEPY / POWERDOWN** | Gentle powering-down whistle slowly trailing into silence ($1800\text{Hz} \rightarrow 250\text{Hz}$). |
| `"Let me think about that for a moment..."` | **THINKING / CHATTER** | Staccato computing chatter blips with micro pitch bends ($1400\text{Hz} \rightarrow 1800\text{Hz}$). |
| `"You are my favorite buddy!"` | **AFFECTION / WARM** | Warm melodic whistle phrase with gentle upward vibrato ($1200\text{Hz} \rightarrow 2800\text{Hz}$). |

---

## 3. Directory Structure

```
tests/audio/
├── README.md                           # Documentation and sentence replication guide
├── sonic_emotion.py                    # R2-D2 Engine, Sentence Prosody Analyzer, WAV synthesizer
├── test_sonic_emotion.py               # Automated unit & behavior tests (16 tests)
├── interactive_test.py                 # Interactive CLI: type ANY sentence to hear droid replication!
└── esp32_sonic_speaker/
    └── esp32_sonic_speaker.ino         # Standalone non-blocking ESP32 firmware with glissando sweeps
```

---

## 4. How to Test with Sentences

Run the interactive test tool:
```powershell
python interactive_test.py
```

### Try Typing Sentences Directly:
- Type: `I found the object you were looking for!`
- Type: `Can you see what I am wearing?`
- Type: `I am very sad and disappointed today...`
- Type: `Stop! Warning danger ahead!`
- Type: `I am so sleepy, good night.`
- Type: `Hello there, my friend!`

The system will:
1. Detect emotion, intensity, and sentence cadence.
2. Render an ASCII pitch sweep ladder.
3. Immediately play the authentic R2-D2 vocalization through your PC speakers.
4. Transmit the command to the ESP32 hardware speaker if connected!

### Other Test Controls:
- Key shortcuts: `1` (Happy), `2` (Excited), `3` (Sad), `4` (Angry), `5` (Confused), `6` (Surprised), `7` (Thinking), `8` (Success), `9` (Error), `0` (Neutral).
- Type `demo` to hear an automated showcase tour of multiple sentences.
- Type `i 0.8` to adjust intensity from 0.0 to 1.0.
- Type `esp 192.168.1.37` to configure the target ESP32 robot IP.

---

## 5. Automated Verification

Run the test suite:
```powershell
python -m unittest tests/audio/test_sonic_emotion.py
```
**Status**: 16 unit tests covering all 18+ emotions, continuous frequency sweeps, sentence prosody translation, boundary conditions, and WAV synthesis are **100% Passed**.
