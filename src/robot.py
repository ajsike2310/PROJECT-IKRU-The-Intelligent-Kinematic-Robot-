import websocket
import time


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

    def forward(self, duration=0):

        self.send("FORWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()


    def backward(self, duration=0):

        self.send("BACKWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()


    def left(self, duration=0):

        self.send("LEFT")
        if duration > 0:
            time.sleep(duration)
            self.stop()


    def right(self, duration=0):

        self.send("RIGHT")
        if duration > 0:
            time.sleep(duration)
            self.stop()


    def stop(self, duration=0):

        self.send("STOP")
        if duration > 0:
            time.sleep(duration)


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
    # SPECIAL ACTIONS
    # ============================================================

    def dance(self):
        """Perform a cute random dance with motors and eyes."""
        moves = [
            ("LEFT", "GLEE", 0.4),
            ("RIGHT", "HAPPY", 0.4),
            ("LEFT", "SURPRISED", 0.4),
            ("RIGHT", "GLEE", 0.4),
            ("FORWARD", "HAPPY", 0.4),
            ("BACKWARD", "GLEE", 0.4),
        ]
        for move, emotion, duration in moves:
            self.send(move)
            self.send(emotion)
            time.sleep(duration)
            self.send("STOP")
        self.send("NORMAL")

    def sing(self):
        """Sing a song by displaying notes, swaying, and showing emotions."""
        notes = ["♪", "♫", "♪♪", "♬"]
        self.display_open()
        time.sleep(0.3)
        for i in range(4):
            self.send("HAPPY" if i % 2 == 0 else "GLEE")
            self.send("LEFT" if i % 2 == 0 else "RIGHT")
            self.display(f"   {notes[i]}   ")
            time.sleep(1.2)
            self.send("STOP")
        self.display_close()
        time.sleep(0.3)
        self.send("NORMAL")

    # ============================================================
    # OLED DISPLAY
    # ============================================================

    def display(self, text):

        self.send(
            "DISPLAY:" + text
        )


    def display_open(self):
        """Open the speech box (persistent mode — stays open until display_close)."""

        self.send("DISPLAY_OPEN")


    def display_close(self):
        """Close the speech box and return to eye mode."""

        self.send("DISPLAY_CLOSE")


    # ============================================================
    # CLOSE CONNECTION
    # ============================================================

    def close(self):

        self.ws.close()