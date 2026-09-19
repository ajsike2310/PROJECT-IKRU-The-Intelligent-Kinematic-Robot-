import websocket
import time

ws = websocket.WebSocket()
ws.connect("ws://10.252.106.144:81")
print("Connected!")
ws.send("GET_DISTANCE")
ws.settimeout(2.0)
try:
    print("Waiting for response...")
    reply = ws.recv()
    print("Received:", reply)
except Exception as e:
    print("Error:", e)
finally:
    ws.close()
