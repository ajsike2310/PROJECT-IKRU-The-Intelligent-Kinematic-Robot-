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
    # These functions invoke the corresponding C++ GoTo_* functions
    # running on the ESP32 via the esp32-eyes Face library.
    # ============================================================

    def normal(self):

        self.send("NORMAL")


    def happy(self):

        self.send("HAPPY")


    def glee(self):

        self.send("GLEE")


    def sad(self):

        self.send("SAD")


    def worried(self):

        self.send("WORRIED")


    def focused(self):

        self.send("FOCUSED")


    def annoyed(self):

        self.send("ANNOYED")


    def surprised(self):

        self.send("SURPRISED")


    def skeptic(self):

        self.send("SKEPTIC")


    def frustrated(self):

        self.send("FRUSTRATED")


    def unimpressed(self):

        self.send("UNIMPRESSED")


    def sleepy(self):

        self.send("SLEEPY")


    def suspicious(self):

        self.send("SUSPICIOUS")


    def squint(self):

        self.send("SQUINT")


    def angry(self):

        self.send("ANGRY")


    def furious(self):

        self.send("FURIOUS")


    def scared(self):

        self.send("SCARED")


    def awe(self):

        self.send("AWE")


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