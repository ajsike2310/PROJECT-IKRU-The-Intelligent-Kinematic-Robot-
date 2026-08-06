import json
import ollama

from robot import Robot

# -----------------------------
# Connect to ESP32
# -----------------------------
robot = Robot(ip="192.168.1.44")

# -----------------------------
# Available robot functions
# -----------------------------
functions = {
    "forward": robot.forward,
    "backward": robot.backward,
    "left": robot.left,
    "right": robot.right,
    "stop": robot.stop,
}

# -----------------------------
# System Prompt
# -----------------------------
SYSTEM_PROMPT = """
You are an AI assistant controlling a robot.

The robot has these tools:

forward
backward
left
right
stop

Rules:

1. If the user's request requires robot movement, respond ONLY with JSON.

Examples:

{"tool":"forward"}

{"tool":"left"}

{"tool":"right"}

{"tool":"backward"}

{"tool":"stop"}

2. Do NOT include markdown.

3. Do NOT explain the JSON.

4. If the request is not asking the robot to move, answer normally like ChatGPT.

Examples:

User: Hello
Assistant: Hello! How can I help you today?

User: What is Python?
Assistant: Python is a programming language...

User: Move forward
Assistant:
{"tool":"forward"}

User: Can you turn left?
Assistant:
{"tool":"left"}

User: Stop
Assistant:
{"tool":"stop"}
"""

# -----------------------------
# Chat History
# -----------------------------
messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]

print("=" * 50)
print("🤖 Robot Assistant Started")
print("Type 'exit' to quit")
print("=" * 50)

while True:

    user = input("\nYou: ")

    if user.lower() == "exit":
        break

    messages.append({
        "role": "user",
        "content": user
    })

    response = ollama.chat(
        model="phi3:3.8b-mini-4k-instruct-q4_K_M",
        messages=messages
    )

    assistant = response["message"]["content"].strip()

    # Save assistant response
    messages.append({
        "role": "assistant",
        "content": assistant
    })

    # ---------------------------------
    # Check if model returned JSON
    # ---------------------------------
    try:

        data = json.loads(assistant)

        if "tool" in data:

            tool = data["tool"].lower()

            if tool in functions:

                print(f"\n🔧 Executing: {tool}")

                result = functions[tool]()

                print("Robot:", result)

            else:

                print("Unknown tool:", tool)

        else:

            print("Assistant:", assistant)

    except json.JSONDecodeError:

        print("\nAssistant:", assistant)

# -----------------------------
# Cleanup
# -----------------------------
robot.close()