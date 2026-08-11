import websocket


class Robot:

    def __init__(self, ip):

        self.ws = websocket.create_connection(
            f"ws://{ip}:81"
        )


    # ============================================================
    # SEND COMMAND
    # ============================================================

    def send(self, cmd):

        self.ws.send(cmd)

        print(self.ws.recv())


    # ============================================================
    # MOVEMENT
    # ============================================================

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


    # ============================================================
    # EMOTIONS
    #
    # These functions invoke the corresponding C++ functions
    # running on the ESP32.
    # ============================================================

    def happy(self):

        self.send("HAPPY")


    def sad(self):

        self.send("SAD")


    def angry(self):

        self.send("ANGRY")


    def excited(self):

        self.send("EXCITED")


    def surprised(self):

        self.send("SURPRISED")


    def thinking(self):

        self.send("THINKING")


    def sleepy(self):

        self.send("SLEEPY")


    def worried(self):

        self.send("WORRIED")


    def idle(self):

        self.send("IDLE")


    # ============================================================
    # OLED DISPLAY
    # ============================================================

    def display(self, text):

        self.send(
            "DISPLAY:" + text
        )


    # ============================================================
    # CLOSE CONNECTION
    # ============================================================

    def close(self):

        self.ws.close()