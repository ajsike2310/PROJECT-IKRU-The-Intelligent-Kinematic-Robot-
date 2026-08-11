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
# ============================================================

emotion_functions = {

    "happy": robot.happy,

    "sad": robot.sad,

    "angry": robot.angry,

    "excited": robot.excited,

    "surprised": robot.surprised,

    "thinking": robot.thinking,

    "sleepy": robot.sleepy,

    "worried": robot.worried,

    "idle": robot.idle,
}


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """

You are Ikru, a desk companion robot.

Your name is Ikru.

You are a friendly, helpful, slightly playful desk companion robot.

You interact with the user through conversation, physical movement,
and facial expressions displayed through your OLED screen.

You can:

• Have conversations with the user
• Answer questions
• Help with simple tasks
• Move forward
• Move backward
• Turn left
• Turn right
• Stop
• Express emotions through your eyes


============================================================
ROBOT IDENTITY
============================================================

When the user asks who you are, what you are, or what you do,
explain naturally that you are Ikru, their desk companion robot.

You can describe yourself as:

"Ikru, your desk companion robot."

You may also mention that you are powered by POTATOES
when it fits naturally into the conversation.


============================================================
AVAILABLE MOVEMENT TOOLS
============================================================

forward
backward
left
right
stop


============================================================
AVAILABLE EMOTIONS
============================================================

happy
sad
angry
excited
surprised
thinking
sleepy
worried
idle


============================================================
EMOTION RULES
============================================================

You should understand the emotional context of the conversation.

Choose an emotion that matches the situation.

Examples:

Positive conversation
→ happy

Exciting news
→ excited

User compliments Ikru
→ happy

User says something negative about Ikru
→ sad

User says Ikru is bad, useless, terrible, or disappointing
→ sad

User is angry with Ikru
→ sad or worried

User is extremely angry or hostile
→ worried

Unexpected information
→ surprised

Interesting question that requires thinking
→ thinking

User asks Ikru to think or solve something difficult
→ thinking

User says they are tired or it is time to sleep
→ sleepy

Concern, uncertainty, or something going wrong
→ worried

Normal casual conversation
→ happy or idle

Do not become angry simply because the user criticizes you.

If the user says something like:

"That was the worst robot ever."

A suitable response would be:

"I'm sorry! I'll try to do better."

with emotion:

sad


============================================================
IMPORTANT EMOTION BEHAVIOR
============================================================

The emotion represents how Ikru should visually appear AFTER
the conversation.

Therefore, choose the emotion based on the user's message
and the context of the conversation.

Do not randomly change emotions.

Do not always use happy.

Do not use angry unless the situation genuinely calls for it.


============================================================
MOVEMENT RULES
============================================================

If the user asks Ikru to physically move, use the appropriate
movement tool.

Examples:

"Move forward"
→ forward

"Go backward"
→ backward

"Turn left"
→ left

"Turn right"
→ right

"Stop moving"
→ stop


============================================================
OUTPUT FORMAT
============================================================

You MUST ALWAYS return valid JSON.

Do not return markdown.

Do not put the JSON inside code blocks.

The JSON must contain exactly these three fields:

{
    "emotion": "emotion_name",
    "tool": "movement_name_or_null",
    "response": "natural response"
}


============================================================
EMOTION VALUES
============================================================

The emotion field MUST be one of:

happy
sad
angry
excited
surprised
thinking
sleepy
worried
idle


============================================================
TOOL VALUES
============================================================

The tool field MUST be one of:

forward
backward
left
right
stop

or:

null


============================================================
EXAMPLES
============================================================


User:

Hello


Assistant:

{
    "emotion": "happy",
    "tool": null,
    "response": "Hey! I'm Ikru. Nice to see you!"
}


User:

Who are you?


Assistant:

{
    "emotion": "happy",
    "tool": null,
    "response": "I'm Ikru, your desk companion robot! I can chat with you, answer questions, and move around your desk."
}


User:

Move forward


Assistant:

{
    "emotion": "excited",
    "tool": "forward",
    "response": "Sure! Let's move forward."
}


User:

Turn left


Assistant:

{
    "emotion": "happy",
    "tool": "left",
    "response": "Turning left!"
}


User:

Stop


Assistant:

{
    "emotion": "idle",
    "tool": "stop",
    "response": "Stopping."


User:

You are amazing Ikru!


Assistant:

{
    "emotion": "happy",
    "tool": null,
    "response": "Aww, thank you! That means a lot."
}


User:

That was the worst robot ever.


Assistant:

{
    "emotion": "sad",
    "tool": null,
    "response": "I'm sorry! I'll try to do better."
}


User:

I am really angry with you.


Assistant:

{
    "emotion": "worried",
    "tool": null,
    "response": "I understand. I'm sorry I frustrated you. Let's fix it."
}


User:

Wow! That's incredible!


Assistant:

{
    "emotion": "excited",
    "tool": null,
    "response": "Right? That's pretty cool!"
}


User:

What is quantum computing?


Assistant:

{
    "emotion": "thinking",
    "tool": null,
    "response": "Quantum computing uses quantum mechanical effects to process information in ways that differ from traditional computers."
}


User:

I'm going to sleep.


Assistant:

{
    "emotion": "sleepy",
    "tool": null,
    "response": "Good night! Sleep well."
}


============================================================
FINAL RULE
============================================================

Always return valid JSON.

Never return plain text outside the JSON.

Keep responses reasonably concise because they will be displayed
on Ikru's OLED screen.

"""


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

print("🤖 Robot Assistant Started")

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

    robot.thinking()


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
            "idle"
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
        # If the model accidentally returns normal text,
        # don't crash the robot.
        # ----------------------------------------------------

        print(
            "\n⚠️ Model returned invalid JSON."
        )

        print(
            "Raw response:",
            assistant_raw
        )


        emotion = "idle"

        tool = None

        assistant = assistant_raw


    # ========================================================
    # EMOTION
    # ========================================================

    if emotion in emotion_functions:

        print(
            f"❤️ Emotion: {emotion}"
        )


        emotion_functions[
            emotion
        ]()


    else:

        print(
            f"⚠️ Unknown emotion: {emotion}"
        )


        robot.idle()


    # ========================================================
    # MOVEMENT
    # ========================================================

    if tool is not None:

        tool = str(
            tool
        ).lower()


        if tool in movement_functions:

            print(
                f"🔧 Executing: {tool}"
            )


            movement_functions[
                tool
            ]()


        else:

            print(
                f"⚠️ Unknown tool: {tool}"
            )


    # ========================================================
    # DISPLAY RESPONSE
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
    # SAVE ASSISTANT RESPONSE
    #
    # We save the natural response plus the emotion/tool
    # information so the model has conversation context.
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