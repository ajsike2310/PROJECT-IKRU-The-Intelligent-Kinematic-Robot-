"""
===============================================================================
PROJECT IKRU — ULTRASONIC SENSOR TEST
===============================================================================
Tests the ultrasonic sensor connected directly to the ESP32-WROOM.
Continuously reads distance and triggers an alert when an object gets close.
===============================================================================
"""

import sys
import os
import time
import argparse

# Ensure 'software' directory is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
software_dir = os.path.join(project_root, "software")
if software_dir not in sys.path:
    sys.path.insert(0, software_dir)

from ikru.robot import RobotController

def test_ultrasonic_detection(robot_ip="192.168.1.34", threshold_cm=30.0):
    print("=" * 70)
    print("  IKRU: Ultrasonic Distance Sensor Test (ESP32-WROOM)")
    print("=" * 70)

    # 1. Initialize Robot (for Ultrasonic)
    print(f"[*] Connecting to Body Controller at {robot_ip}...")
    robot = RobotController(ip=robot_ip)
    if not robot.connected:
        print("[-] Failed to connect to robot controller. Check IP and Wi-Fi.")
        return
    print("[+] Robot Controller connected.")

    print("\n[+] Setup complete! Move an object in front of IKRU.")
    print(f"    (Trigger distance: < {threshold_cm} cm)")
    print("    Press Ctrl+C to stop.\n")

    cooldown = 2.0  # Wait 2 seconds before triggering again
    last_trigger_time = 0

    try:
        while True:
            # Poll distance
            dist = robot.get_distance(timeout=1.0)
            
            status = "CLEAR"
            if dist > 0 and dist < threshold_cm:
                status = "OBJECT CLOSE!"
                
                # Check cooldown
                if time.time() - last_trigger_time > cooldown:
                    print(f"\n[!] Object detected at {dist:.1f} cm!")
                    # Optionally add robot reactions here
                    
                    last_trigger_time = time.time()
                    print("[*] Waiting for next object...")
            
            # Print status line
            if dist > 0 and dist < 999:
                print(f"\r  Distance: {dist:5.1f} cm | Status: {status}    ", end="", flush=True)
            else:
                print(f"\r  Distance: OUT OF RANGE | Status: {status}    ", end="", flush=True)
                
            time.sleep(0.2)
            
    except KeyboardInterrupt:
        print("\n\n[*] Stopping test.")
    finally:
        robot.stop()
        print("[+] Cleanup complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ultrasonic Distance Test")
    parser.add_argument("--robot-ip", default="192.168.1.34", help="ESP32 Controller IP")
    parser.add_argument("--thresh", type=float, default=30.0, help="Distance threshold in cm")
    args = parser.parse_args()

    test_ultrasonic_detection(
        robot_ip=args.robot_ip,
        threshold_cm=args.thresh
    )
