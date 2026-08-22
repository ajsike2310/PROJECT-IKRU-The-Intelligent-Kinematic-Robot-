// ============================================================
// IKRU EYES — ESP32-CAM FIRMWARE
//
// Hardware: AI-Thinker ESP32-CAM (OV2640)
//
// Endpoints:
//   http://<ip>/         — Live preview web page
//   http://<ip>/stream   — MJPEG stream
//   http://<ip>/capture  — Single JPEG snapshot
//
// ESP32 Arduino Core: 3.x
// ============================================================

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

// ============================================================
// WiFi
// ============================================================

const char* ssid     = "GNXS-2.4G-C457E1";
const char* password = "1234567890";

// ============================================================
// AI-THINKER ESP32-CAM PIN MAP
// ============================================================

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0

#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ============================================================
// SERVER
// ============================================================

WebServer server(80);

// ============================================================
// CAMERA INITIALIZATION
// ============================================================

void setupCamera()
{
    camera_config_t config = {};

    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;

    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;

    config.pin_xclk  = XCLK_GPIO_NUM;
    config.pin_pclk  = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href  = HREF_GPIO_NUM;

    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;

    config.pin_pwdn  = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;

    config.xclk_freq_hz = 20000000;

    // JPEG is best for WiFi streaming
    config.pixel_format = PIXFORMAT_JPEG;

    // ========================================================
    // LOW LATENCY SETTINGS
    // ========================================================

    // 320x240
    config.frame_size = FRAMESIZE_QVGA;

    // Higher number = smaller JPEG = faster transmission
    config.jpeg_quality = 15;

    if (psramFound())
    {
        // Two buffers allow the camera to capture
        // the next frame while the previous frame
        // is being transmitted.
        config.fb_count = 2;

        // Always prefer the newest frame.
        config.grab_mode = CAMERA_GRAB_LATEST;

        Serial.println("[CAM] PSRAM detected");
        Serial.println("[CAM] Resolution: QVGA 320x240");
        Serial.println("[CAM] Frame buffers: 2");
    }
    else
    {
        config.fb_count = 1;

        config.grab_mode =
            CAMERA_GRAB_WHEN_EMPTY;

        Serial.println("[CAM] WARNING: PSRAM not detected");
        Serial.println("[CAM] Frame buffers: 1");
    }

    esp_err_t err =
        esp_camera_init(&config);

    if (err != ESP_OK)
    {
        Serial.printf(
            "[CAM] Initialization failed: 0x%x\n",
            err
        );

        while (true)
        {
            delay(1000);
        }
    }

    // ========================================================
    // OV2640 SENSOR SETTINGS
    // ========================================================

    sensor_t* sensor =
        esp_camera_sensor_get();

    if (sensor)
    {
        sensor->set_brightness(
            sensor,
            0
        );

        sensor->set_contrast(
            sensor,
            0
        );

        sensor->set_saturation(
            sensor,
            0
        );

        sensor->set_whitebal(
            sensor,
            1
        );

        sensor->set_awb_gain(
            sensor,
            1
        );

        sensor->set_exposure_ctrl(
            sensor,
            1
        );

        sensor->set_gain_ctrl(
            sensor,
            1
        );

        sensor->set_hmirror(
            sensor,
            0
        );

        sensor->set_vflip(
            sensor,
            0
        );
    }

    Serial.println("[CAM] Camera initialized successfully");
}

// ============================================================
// WEB PAGE
// ============================================================

void handleRoot()
{
    const char* html = R"rawliteral(
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>IKRU Eyes</title>

<style>

body {
    background: #11111b;
    color: #cdd6f4;
    font-family: Arial, sans-serif;
    text-align: center;
    margin: 0;
    padding: 20px;
}

h1 {
    color: #f5c2e7;
    margin-bottom: 5px;
}

p {
    color: #a6adc8;
}

.container {
    display: inline-block;
    padding: 10px;
    background: #181825;
    border: 2px solid #b4befe;
    border-radius: 12px;
}

img {
    display: block;
    width: 320px;
    height: 240px;
    object-fit: contain;
    border-radius: 8px;
}

.info {
    margin-top: 20px;
}

a {
    color: #89b4fa;
    text-decoration: none;
}

button {
    margin: 5px;
    padding: 10px 15px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
}

</style>

</head>

<body>

<h1>🤖 IKRU Eyes</h1>

<p>ESP32-CAM Live Vision</p>

<div class="container">

    <img src="/stream">

</div>

<div class="info">

    <p>
        <a href="/stream" target="_blank">
            Open Stream
        </a>
    </p>

    <p>
        <a href="/capture" target="_blank">
            Take Snapshot
        </a>
    </p>

</div>

</body>

</html>
)rawliteral";

    server.send(
        200,
        "text/html",
        html
    );
}

// ============================================================
// MJPEG STREAM
// ============================================================
// 2. MJPEG STREAM — consumed by vision.py
void handleStream() {
  WiFiClient client = server.client();

  // Send multipart MIME header
  String header =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
    "Access-Control-Allow-Origin: *\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: close\r\n\r\n";
  client.print(header);

  Serial.println("[CAM] Stream started");

  while (client.connected()) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAM] Frame capture failed");
      break;
    }

    String frame_header = 
      "--frame\r\n"
      "Content-Type: image/jpeg\r\n"
      "Content-Length: " + String(fb->len) + "\r\n\r\n";
      
    client.print(frame_header);
    client.write(fb->buf, fb->len);
    client.print("\r\n");

    esp_camera_fb_return(fb);

    // Give some breathing room for the WiFi stack
    delay(30);
  }

  client.stop();
  Serial.println("[CAM] Stream stopped");
}

// 3. JPEG SNAPSHOT — single still image
void handleCapture() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }
  
  WiFiClient client = server.client();
  String header = 
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: image/jpeg\r\n"
    "Content-Disposition: inline; filename=capture.jpg\r\n"
    "Access-Control-Allow-Origin: *\r\n"
    "Content-Length: " + String(fb->len) + "\r\n"
    "Connection: close\r\n\r\n";
    
  client.print(header);
  client.write(fb->buf, fb->len);
  
  esp_camera_fb_return(fb);
}

// ============================================================
// SETUP
// ============================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);

    Serial.println();
    Serial.println(
        "================================"
    );

    Serial.println(
        "        IKRU EYES"
    );

    Serial.println(
        "     ESP32-CAM VISION"
    );

    Serial.println(
        "================================"
    );

    // Camera
    setupCamera();

    // ========================================================
    // WiFi
    // ========================================================

    WiFi.mode(
        WIFI_STA
    );

    // Disable WiFi power saving
    // for lower latency.
    WiFi.setSleep(
        false
    );

    Serial.print(
        "[WiFi] Connecting to "
    );

    Serial.println(
        ssid
    );

    WiFi.begin(
        ssid,
        password
    );

    int attempts = 0;

    while (
        WiFi.status() != WL_CONNECTED &&
        attempts < 40
    )
    {
        delay(250);

        Serial.print(
            "."
        );

        attempts++;
    }

    Serial.println();

    if (
        WiFi.status() != WL_CONNECTED
    )
    {
        Serial.println(
            "[WiFi] CONNECTION FAILED"
        );

        Serial.println(
            "[WiFi] Check SSID/password"
        );

        while (true)
        {
            delay(1000);
        }
    }

    Serial.println(
        "[WiFi] Connected!"
    );

    Serial.print(
        "[WiFi] IP: http://"
    );

    Serial.println(
        WiFi.localIP()
    );

    // ========================================================
    // HTTP ROUTES
    // ========================================================

    server.on(
        "/",
        handleRoot
    );

    server.on(
        "/stream",
        handleStream
    );

    server.on(
        "/capture",
        handleCapture
    );

    server.begin();

    Serial.println(
        "[HTTP] Server started"
    );

    Serial.println();
    Serial.println(
        "================================"
    );

    Serial.println(
        "       IKRU EYES READY"
    );

    Serial.println(
        "================================"
    );

    Serial.print(
        "Open: http://"
    );

    Serial.println(
        WiFi.localIP()
    );

    Serial.println();
}

// ============================================================
// LOOP
// ============================================================

void loop()
{
    server.handleClient();
}