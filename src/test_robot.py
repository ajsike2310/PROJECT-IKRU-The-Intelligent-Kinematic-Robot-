import websocket

IP = "10.110.131.144"

print("Connecting...")

ws = websocket.create_connection(
    f"ws://{IP}:81",
    timeout=10,
    http_proxy_host=None,
    http_proxy_port=None
)

print("CONNECTED!")

ws.send("DISPLAY:Hello from Python!")

print("ESP32 replied:")
print(ws.recv())

ws.close()

print("DONE")