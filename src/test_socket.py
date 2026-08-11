import socket

IP = "10.110.131.144"
PORT = 81

print(f"Testing TCP connection to {IP}:{PORT}")

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)

try:
    sock.connect((IP, PORT))

    print("TCP CONNECTION SUCCESSFUL!")
    print("ESP32 port 81 is reachable.")

except Exception as e:

    print("TCP CONNECTION FAILED!")
    print(type(e).__name__, e)

finally:

    sock.close()