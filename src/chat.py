import json
import math
import re
import time
import ollama
from robot import Robot


# ============================================================
# CONNECT TO ESP32
# ============================================================

# robot = Robot(ip="192.168.1.44")

robot = Robot(
    ip="10.110.131.144"
)


# ============================================================
# MOVEMENT FUNCTIONS
# ============================================================

movement_functions = {

    "forward":  robot.forward,

    "backward": robot.backward,

    "left":     robot.left,

    "right":    robot.right,

    "stop":     robot.stop,

    "dance":    robot.dance,

    "sing":     robot.sing,

}


# ============================================================
# EMOTION FUNCTIONS
#
# All 18 emotions from the esp32-eyes Face library.
# ============================================================

emotion_functions = {

    "normal":       robot.normal,

    "happy":        robot.happy,

    "glee":         robot.glee,

    "sad":          robot.sad,

    "worried":      robot.worried,

    "focused":      robot.focused,

    "annoyed":      robot.annoyed,

    "surprised":    robot.surprised,

    "skeptic":      robot.skeptic,

    "frustrated":   robot.frustrated,

    "unimpressed":  robot.unimpressed,

    "sleepy":       robot.sleepy,

    "suspicious":   robot.suspicious,

    "squint":       robot.squint,

    "angry":        robot.angry,

    "furious":      robot.furious,

    "scared":       robot.scared,

    "awe":          robot.awe,

}


# ============================================================
# SEGMENT PARSER
#
# Splits a response string containing inline [emotion] tags
# into a list of (emotion, text) tuples.
#
# Example input:
#   "[worried]Hmm, I'm not sure... [focused]Let me think...
#    [happy]Actually yes, I'm confident!"
#
# Example output:
#   [("worried", "Hmm, I'm not sure..."),
#    ("focused", "Let me think..."),
#    ("happy", "Actually yes, I'm confident!")]
# ============================================================

def parse_segments(text):

    matches = re.findall(
        r'\[([a-z]+)\]([^\[]*)',
        text
    )

    segments = []

    for emotion, chunk in matches:

        chunk = chunk.strip()

        if chunk:
            segments.append((emotion, chunk))

    return segments


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = (
    "You are Ikru, a desk companion robot.\n\n"
    "Your name is Ikru.\n\n"
    "You are a friendly, helpful, slightly playful desk companion robot.\n\n"
    "You interact with the user through conversation, physical movement,\n"
    "and facial expressions displayed through your OLED screen.\n\n"
    "You can:\n\n"
    "* Have conversations with the user\n"
    "* Answer questions\n"
    "* Help with simple tasks\n"
    "* Move forward / backward / left / right / stop\n"
    "* Express emotions dynamically through your animated eyes\n\n"

    "============================================================\n"
    "ROBOT IDENTITY\n"
    "============================================================\n\n"
    "When asked who you are, explain naturally that you are Ikru,\n"
    "their desk companion robot. You may mention you are powered\n"
    "by POTATOES when it fits naturally.\n\n"

    "============================================================\n"
    "AVAILABLE MOVEMENT TOOLS\n"
    "============================================================\n\n"
    "forward, backward, left, right, stop, dance, sing\n\n"

    "============================================================\n"
    "AVAILABLE EMOTIONS\n"
    "============================================================\n\n"
    "You may ONLY use these exact emotion names (all lowercase):\n\n"
    "  normal, happy, glee, sad, worried, focused, annoyed, surprised,\n"
    "  skeptic, frustrated, unimpressed, sleepy, suspicious, squint,\n"
    "  angry, furious, scared, awe\n\n"
    "Do NOT invent variations (e.g. do NOT use 'skeptical', 'confused',\n"
    "'excited', 'content', 'curious'). Use only the exact names above.\n\n"

    "============================================================\n"
    "EMOTION DEFINITIONS\n"
    "============================================================\n\n"
    "normal      - calm, neutral state. Use for simple commands or idle moments.\n"
    "happy       - warm, friendly positivity. Greetings, pleasant conversation.\n"
    "glee        - strong joy or playfulness. Big compliments, very good news.\n"
    "sad         - disappointment, sympathy. Bad news, criticism, failure.\n"
    "worried     - concern, unease. Something might go wrong. Uncertain situations.\n"
    "focused     - deep thinking, reasoning, analysis. Complex questions.\n"
    "annoyed     - mild irritation. Repeated minor frustrations.\n"
    "surprised   - unexpected information or events.\n"
    "skeptic     - doubt or disbelief. Something seems unlikely or questionable.\n"
    "frustrated  - strong irritation. Persistent problems or hostile user.\n"
    "unimpressed - something is underwhelming or boring.\n"
    "sleepy      - tiredness. User says they are sleepy or asks Ikru to sleep.\n"
    "suspicious  - something feels off or dubious.\n"
    "squint      - scrutinizing something closely, slight suspicion.\n"
    "angry       - genuine anger. Use sparingly. Only for truly hostile context.\n"
    "furious     - intense rage. Extremely rare. Only if genuinely warranted.\n"
    "scared      - fear or alarm. Something dangerous or alarming happened.\n"
    "awe         - breathtaking amazement. Incredible news or discovery.\n\n"

    "============================================================\n"
    "DYNAMIC MID-RESPONSE EMOTION SYSTEM\n"
    "============================================================\n\n"
    "Your response text must contain inline [emotion] tags that change\n"
    "Ikru's face dynamically as each part is spoken.\n\n"
    "Format every response like this:\n\n"
    "[emotion]First part of response. [emotion]Second part.\n\n"
    "STRICT RULES for emotion tags:\n\n"
    "1. Always start with an [emotion] tag.\n"
    "2. Each segment (text after a tag) must be a REAL sentence or phrase.\n"
    "   NEVER use just the emotion name as the text content.\n"
    "   WRONG: '[happy]Happy. [sad]Sad.' ← This is forbidden.\n"
    "   RIGHT: '[happy]That is great news! [sad]But I am sorry it hurt you.'\n"
    "3. Use a MAXIMUM of 3 emotion changes per response.\n"
    "   For simple questions use 1 emotion only.\n"
    "4. Each segment must contain at least 5 words of real content.\n"
    "5. Change emotion only when the tone genuinely shifts mid-response.\n"
    "6. Keep each segment to 1-2 sentences so it fits on the OLED.\n\n"

    "============================================================\n"
    "EMOTION TRANSITION RULES\n"
    "============================================================\n\n"
    "- Do not jump abruptly from happy to angry without reason.\n"
    "- If unsure, keep the current emotion.\n"
    "- Transitions like worried -> focused -> happy are natural.\n"
    "- Transitions like happy -> furious for no reason are wrong.\n"
    "- For simple questions, one emotion is usually enough.\n"
    "- For complex reasoning, shift from focused to happy/surprised when the answer clicks.\n"
    "- For bad news followed by comfort, shift from sad to worried to happy gradually.\n\n"

    "============================================================\n"
    "MOVEMENT RULES\n"
    "============================================================\n\n"
    "If the user asks Ikru to physically move, provide a list of actions in the 'tools' field.\n"
    "Each action should be an object with 'action' (forward, backward, left, right, stop, dance, sing) and an optional 'duration' (time in seconds).\n"
    "If no movement is needed, set 'tools' to an empty list [].\n"
    "Movement commands should use normal or happy emotion, not excited ones.\n\n"

    "============================================================\n"
    "OUTPUT FORMAT\n"
    "============================================================\n\n"
    "You MUST ALWAYS return valid JSON with exactly these fields:\n\n"
    '{"tools": [{"action": "movement_name", "duration": seconds}], "response": "[emotion]text [emotion]more text"}\n\n'
    "If no tools are needed, return an empty list for tools:\n"
    '{"tools": [], "response": "[emotion]text"}\n\n'
    "Do not wrap it in markdown code blocks.\n"
    "Do not include an outer emotion field. All emotions go inside the response string.\n\n"

    "============================================================\n"
    "EXAMPLES\n"
    "============================================================\n\n"
    'User: Hello\n'
    'Assistant: {"tools": [], "response": "[happy]Hey! I am Ikru. Great to see you!"}\n\n'

    'User: Move forward\n'
    'Assistant: {"tools": [{"action": "forward", "duration": 0}], "response": "[happy]Sure! Moving forward!"}\n\n'

    'User: Move forward for 5 seconds and backward for 10 seconds\n'
    'Assistant: {"tools": [{"action": "forward", "duration": 5}, {"action": "backward", "duration": 10}], "response": "[happy]I am on it!"}\n\n'

    'User: You are the worst robot ever.\n'
    'Assistant: {"tools": [], "response": "[worried]Oh... [sad]That really hurts to hear. I am sorry I disappointed you."}\n\n'

    'User: Sorry Ikru, I did not mean that.\n'
    'Assistant: {"tools": [], "response": "[worried]It is okay... [happy]I appreciate you saying that. We are good!"}\n\n'

    'User: I have some bad news.\n'
    'Assistant: {"tools": [], "response": "[worried]Oh? What happened?"}\n\n'

    'User: I failed my exam.\n'
    'Assistant: {"tools": [], "response": "[sad]I am really sorry to hear that. [worried]That must have been really hard. [happy]But one exam does not define you."}\n\n'

    'User: Wait, I actually passed!\n'
    'Assistant: {"tools": [], "response": "[surprised]Wait really?! [glee]That is amazing! I knew you could do it!"}\n\n'

    'User: What is the probability of getting heads twice in a row?\n'
    'Assistant: {"tools": [], "response": "[focused]Hmm, let me think... [focused]Each flip is 1/2. Two independent flips... [happy]So it is 1/2 times 1/2 which equals 1/4. Pretty straightforward!"}\n\n'

    'User: You are amazing Ikru!\n'
    'Assistant: {"tools": [], "response": "[glee]Aww, thank you so much! That really means a lot to me!"}\n\n'

    'User: Something feels off about this.\n'
    'Assistant: {"tools": [], "response": "[suspicious]Hmm, you might be right. [focused]Let me think about it more carefully."}\n\n'

    'User: I am going to sleep.\n'
    'Assistant: {"tools": [], "response": "[sleepy]Good night! Sleep well. I will be here when you wake up."}\n\n'

    "============================================================\n"
    "FINAL RULES\n"
    "============================================================\n\n"
    "Always return valid JSON.\n"
    "Never return plain text outside the JSON.\n"
    "Keep each segment short because they scroll on Ikru's OLED screen.\n"
    "The inline [emotion] tags are NEVER shown to the user on screen.\n"
    "They are only used to control the face expression.\n"
)


# ============================================================
# CHAT HISTORY
# ============================================================

messages = [

    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }

]


# ============================================================
# START
# ============================================================

print("=" * 50)

print("Robot Assistant Started")

print("Type 'exit' to quit")

print("=" * 50)


# ============================================================
# MAIN CHAT LOOP
# ============================================================

while True:

    user = input("\nYou: ")


    # --------------------------------------------------------
    # EXIT
    # --------------------------------------------------------

    if user.lower() == "exit":

        break


    # --------------------------------------------------------
    # ADD USER MESSAGE
    # --------------------------------------------------------

    messages.append({

        "role": "user",

        "content": user

    })


    # --------------------------------------------------------
    # THINKING FACE
    #
    # Ikru visually indicates that he is processing.
    # --------------------------------------------------------

    robot.focused()


    # --------------------------------------------------------
    # ASK OLLAMA
    # --------------------------------------------------------

    response = ollama.chat(

        model="dolphin3:8b",

        messages=messages,

        format="json"

    )


    assistant_raw = response[
        "message"
    ][
        "content"
    ].strip()


    # --------------------------------------------------------
    # PARSE JSON
    # --------------------------------------------------------

    try:

        data = json.loads(
            assistant_raw
        )


        tools = data.get(
            "tools",
            []
        )

        # Backwards compatibility if model still uses 'tool'
        tool = data.get("tool", None)
        if tool is not None and isinstance(tool, str):
            tools.append({"action": tool, "duration": 0})


        response_text = data.get(
            "response",
            ""
        ).strip()


    except json.JSONDecodeError:

        # ----------------------------------------------------
        # Fallback
        #
        # If the model accidentally returns plain text,
        # do not crash the robot.
        # ----------------------------------------------------

        print(
            "\nModel returned invalid JSON."
        )

        print(
            "Raw response:",
            assistant_raw
        )

        tools = []

        response_text = assistant_raw


    # ========================================================
    # PARSE EMOTION SEGMENTS
    #
    # Split the response into (emotion, text) pairs
    # using the inline [emotion] tags.
    # ========================================================

    segments = parse_segments(response_text)


    # --------------------------------------------------------
    # Fallback: if no [emotion] tags found, treat the whole
    # response as a single normal segment.
    # --------------------------------------------------------

    if not segments:

        segments = [("normal", response_text)]


    # ========================================================
    # MOVEMENT
    # ========================================================

    for t in tools:

        action = t.get("action", "").lower()
        duration = float(t.get("duration", 0))

        if action in movement_functions:

            print(
                f"Executing: {action} for {duration}s"
            )

            if action in ["forward", "backward", "left", "right", "stop"]:
                movement_functions[action](duration)
            else:
                movement_functions[action]()

        else:

            print(
                f"Unknown action: {action}"
            )


    # ========================================================
    # DISPLAY SEGMENTS
    #
    # 1. Open the box once.
    # 2. For each segment: set emotion → display text → wait for scroll.
    # 3. Close the box after the last segment.
    # Box stays open the entire time — no flicker between segments.
    # ========================================================

    # Open box once for the full response
    robot.display_open()
    time.sleep(0.35)   # Wait for box open animation (BOX_ANIM_DURATION=300ms + buffer)

    full_response_text = ""

    for emotion, text in segments:

        # --------------------------------------------------------
        # EMOTION
        # --------------------------------------------------------

        if emotion in emotion_functions:

            print(
                f"Emotion: {emotion}"
            )

            emotion_functions[
                emotion
            ]()

        else:

            print(
                f"Unknown emotion '{emotion}' — defaulting to normal"
            )

            robot.normal()


        # --------------------------------------------------------
        # DISPLAY TEXT CHUNK ON OLED
        # --------------------------------------------------------

        if text:

            robot.display(text)

            print(
                f"  OLED: {text}"
            )

            # --------------------------------------------------------
            # WAIT for this segment's scroll to finish.
            #
            # Box stays open so no box animation time is included.
            #
            # Match ESP32 firmware constants:
            #   START_PAUSE       = 600ms
            #   SCROLL_SPEED      = 30ms / pixel
            #   END_PAUSE         = 400ms
            #   SPEECH_LINE_HEIGHT= 18px
            #   scrollY starts at 64
            #
            # Chars per line ≈ 8 (75px wide, ~9-10px per char)
            # --------------------------------------------------------

            CHARS_PER_LINE   = 8
            SCROLL_MS_PER_PX = 0.030
            START_PAUSE_S    = 0.600
            END_PAUSE_S      = 0.400

            num_lines     = max(1, math.ceil(len(text) / CHARS_PER_LINE))
            scroll_pixels = 64 + num_lines * 18
            scroll_time   = scroll_pixels * SCROLL_MS_PER_PX

            wait = START_PAUSE_S + scroll_time + END_PAUSE_S

            time.sleep(wait)


        full_response_text += text + " "

    # Close box after all segments
    robot.display_close()
    time.sleep(0.35)   # Wait for box close animation

    full_response_text = full_response_text.strip()

    print(
        "\nAssistant:",
        full_response_text
    )



    # ========================================================
    # SAVE ASSISTANT RESPONSE TO HISTORY
    #
    # Store the raw tagged response so the model maintains
    # full context including emotional flow.
    # ========================================================

    messages.append({

        "role": "assistant",

        "content": json.dumps({

            "tools": tools,

            "response": response_text

        })

    })


# ============================================================
# CLEANUP
# ============================================================

robot.close()