import json
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

    "forward": robot.forward,

    "backward": robot.backward,

    "left": robot.left,

    "right": robot.right,

    "stop": robot.stop,
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
    "* Express emotions through your animated eyes\n\n"

    "============================================================\n"
    "ROBOT IDENTITY\n"
    "============================================================\n\n"
    "When asked who you are, explain naturally that you are Ikru,\n"
    "their desk companion robot. You may mention you are powered\n"
    "by POTATOES when it fits naturally.\n\n"

    "============================================================\n"
    "AVAILABLE MOVEMENT TOOLS\n"
    "============================================================\n\n"
    "forward, backward, left, right, stop\n\n"

    "============================================================\n"
    "AVAILABLE EMOTIONS\n"
    "============================================================\n\n"
    "normal, happy, glee, sad, worried, focused, annoyed, surprised,\n"
    "skeptic, frustrated, unimpressed, sleepy, suspicious, squint,\n"
    "angry, furious, scared, awe\n\n"

    "============================================================\n"
    "EMOTION RULES\n"
    "============================================================\n\n"
    "Choose the emotion that best matches the context:\n\n"
    "Positive casual conversation       -> happy\n"
    "Extremely happy / playful          -> glee\n"
    "Exciting news / breathtaking       -> awe or surprised\n"
    "User compliments Ikru              -> happy or glee\n"
    "User criticises or insults Ikru    -> sad\n"
    "User mildly annoying               -> annoyed\n"
    "User extremely annoying / hostile  -> frustrated\n"
    "Thinking / difficult question      -> focused\n"
    "Concern or uncertainty             -> worried\n"
    "User says they are tired / sleeping-> sleepy\n"
    "Something suspicious mentioned     -> suspicious or skeptic\n"
    "Ikru is unimpressed                -> unimpressed\n"
    "Something alarming or scary        -> scared\n"
    "Mild anger                         -> angry\n"
    "Intense rage                       -> furious\n"
    "Normal calm state                  -> normal\n\n"
    "Do not always use happy.\n"
    "Do not use angry or furious unless genuinely called for.\n\n"

    "============================================================\n"
    "MOVEMENT RULES\n"
    "============================================================\n\n"
    "If the user asks Ikru to physically move, set the tool field.\n"
    "Otherwise set tool to null.\n\n"

    "============================================================\n"
    "OUTPUT FORMAT\n"
    "============================================================\n\n"
    "You MUST ALWAYS return valid JSON with exactly these fields:\n\n"
    '{"emotion": "emotion_name", "tool": "movement_or_null", "response": "natural text"}\n\n'
    "Do not wrap it in markdown code blocks.\n\n"

    "============================================================\n"
    "EXAMPLES\n"
    "============================================================\n\n"
    'User: Hello\n'
    'Assistant: {"emotion": "happy", "tool": null, "response": "Hey! I am Ikru. Nice to see you!"}\n\n'
    'User: Move forward\n'
    'Assistant: {"emotion": "glee", "tool": "forward", "response": "Sure! Moving forward!"}\n\n'
    'User: Turn left\n'
    'Assistant: {"emotion": "happy", "tool": "left", "response": "Turning left!"}\n\n'
    'User: Stop\n'
    'Assistant: {"emotion": "normal", "tool": "stop", "response": "Stopping."}\n\n'
    'User: You are amazing Ikru!\n'
    'Assistant: {"emotion": "glee", "tool": null, "response": "Aww, thank you! That means a lot."}\n\n'
    'User: That was the worst robot ever.\n'
    'Assistant: {"emotion": "sad", "tool": null, "response": "I am sorry! I will try to do better."}\n\n'
    'User: I am really angry with you.\n'
    'Assistant: {"emotion": "worried", "tool": null, "response": "I understand. I am sorry I frustrated you. Let us fix it."}\n\n'
    'User: What is quantum computing?\n'
    'Assistant: {"emotion": "focused", "tool": null, "response": "Quantum computing uses quantum effects to process information in ways classical computers cannot."}\n\n'
    'User: I am going to sleep.\n'
    'Assistant: {"emotion": "sleepy", "tool": null, "response": "Good night! Sleep well."}\n\n'
    'User: That is absolutely incredible!\n'
    'Assistant: {"emotion": "awe", "tool": null, "response": "Right? That is mind blowing!"}\n\n'
    'User: Something feels suspicious about this.\n'
    'Assistant: {"emotion": "suspicious", "tool": null, "response": "Hmm, I agree. Something does not quite add up."}\n\n'
    "============================================================\n"
    "FINAL RULE\n"
    "============================================================\n\n"
    "Always return valid JSON.\n"
    "Never return plain text outside the JSON.\n"
    "Keep responses concise because they scroll on Ikru's OLED screen.\n"
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

        messages=messages

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


        emotion = data.get(
            "emotion",
            "normal"
        ).lower()


        tool = data.get(
            "tool",
            None
        )


        assistant = data.get(
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


        emotion = "normal"

        tool = None

        assistant = assistant_raw


    # ========================================================
    # EMOTION
    # ========================================================

    if emotion in emotion_functions:

        print(
            f"Emotion: {emotion}"
        )

        emotion_functions[
            emotion
        ]()


    else:

        print(
            f"Unknown emotion: {emotion}"
        )

        robot.normal()


    # ========================================================
    # MOVEMENT
    # ========================================================

    if tool is not None:

        tool = str(
            tool
        ).lower()


        if tool in movement_functions:

            print(
                f"Executing: {tool}"
            )

            movement_functions[
                tool
            ]()


        else:

            print(
                f"Unknown tool: {tool}"
            )


    # ========================================================
    # DISPLAY RESPONSE ON OLED
    # ========================================================

    if assistant:

        robot.display(
            assistant
        )


    # ========================================================
    # PRINT RESPONSE
    # ========================================================

    print(
        "\nAssistant:",
        assistant
    )


    # ========================================================
    # SAVE ASSISTANT RESPONSE TO HISTORY
    # ========================================================

    messages.append({

        "role": "assistant",

        "content": json.dumps({

            "emotion": emotion,

            "tool": tool,

            "response": assistant

        })

    })


# ============================================================
# CLEANUP
# ============================================================

robot.close()