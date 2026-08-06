import websocket


class Robot:

    def __init__(self, ip):

        self.ws = websocket.create_connection(
            f"ws://{ip}:81"
        )

    def send(self, cmd):

        self.ws.send(cmd)

        print(self.ws.recv())

    def forward(self):
        self.send("FORWARD")

    def backward(self):
        self.send("BACKWARD")

    def left(self):
        self.send("LEFT")

    def right(self):
        self.send("RIGHT")

    def stop(self):
        self.send("STOP")

    def close(self):
        self.ws.close()