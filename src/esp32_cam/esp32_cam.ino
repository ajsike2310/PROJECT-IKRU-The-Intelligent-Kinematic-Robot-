// ============================================================
// Required includes MUST be at the top of the file (not inside setup)
// ============================================================
#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include "soc/soc.h"           // For brownout register access
#include "soc/rtc_cntl_reg.h"  // For RTC_CNTL_BROWN_OUT_REG

// ============================================================
// IKRU EYES — ESP32-CAM FIRMWARE
//
// Hardware:
//   AI-Thinker ESP32-CAM Module
//   OV2640 Camera Sensor
//
// Functionality:
//   Connects to WiFi, hosts an HTTP web server on port 80.
//   Serves live MJPEG video stream at /stream, JPEG snapshot at /capture,
//   and an index page at / with a dark theme UI.
// ============================================================

// ============================================================
// CONFIGURATION — Edit these before flashing
// ============================================================

const char *ssid     = "GNXS-2.4G-C457E1";
const char *password = "1234567890";

// Camera Parameters
#define CAMERA_RESOLUTION  FRAMESIZE_QVGA  // QVGA=320x240  VGA=640x480  SVGA=800x600
#define CAMERA_JPEG_QUALITY 12             // 10-63 lower=better quality, larger frames

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
// WEBSERVER GLOBALS
// ============================================================

httpd_handle_t camera_httpd = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY     = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART        = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// ============================================================
// HTTP HANDLERS
// ============================================================

// 1. HTML INDEX PAGE (Dark Theme)
esp_err_t index_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  String ip = WiFi.localIP().toString();
  String html =
    "<html><head><title>IKRU Eyes</title>"
    "<meta name='viewport' content='width=device-width,initial-scale=1.0'>"
    "<style>"
    "body{font-family:'Segoe UI',sans-serif;background:#1e1e2e;color:#cdd6f4;text-align:center;margin:0;padding:20px}"
    "h1{color:#f5c2e7;margin-bottom:5px}"
    "h3{color:#a6adc8;font-weight:400;margin-top:0;margin-bottom:25px}"
    ".container{max-width:650px;margin:auto;background:#313244;padding:30px;border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,.5);border:1px solid #45475a}"
    ".stream-box{background:#11111b;padding:10px;border-radius:12px;border:2px solid #b4befe;display:inline-block}"
    "img{display:block;border-radius:8px;max-width:100%;height:auto}"
    ".info{margin-top:25px;font-size:14px;color:#bac2de;text-align:left;background:#181825;padding:15px;border-radius:8px;border:1px solid #45475a}"
    "p{margin:6px 0}code{background:#313244;color:#f9e2af;padding:2px 6px;border-radius:4px;font-family:Consolas,monospace}"
    "a{color:#89b4fa;text-decoration:none;font-weight:bold}a:hover{color:#94e2d5}"
    "</style></head><body>"
    "<div class='container'>"
    "<h1>🤖 IKRU Eyes</h1><h3>Network Camera Stream</h3>"
    "<div class='stream-box'><img src='/stream'/></div>"
    "<div class='info'>"
    "<p><strong>MJPEG Stream:</strong> <code>http://" + ip + "/stream</code> <a href='/stream' target='_blank'>Open</a></p>"
    "<p><strong>JPEG Snapshot:</strong> <code>http://" + ip + "/capture</code> <a href='/capture' target='_blank'>Open</a></p>"
    "<p><strong>Wi-Fi:</strong> <code>" + String(ssid) + "</code></p>"
    "<p><strong>RSSI:</strong> <code>" + String(WiFi.RSSI()) + " dBm</code></p>"
    "</div></div></body></html>";
  return httpd_resp_send(req, html.c_str(), html.length());
}

// 2. JPEG SNAPSHOT HANDLER
esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] Snapshot capture failed");
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

// 3. LIVE MJPEG STREAM HANDLER
esp_err_t stream_handler(httpd_req_t *req) {
  esp_err_t res = ESP_OK;
  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) return res;

  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "X-Framerate", "30");

  Serial.println("[CAM] Stream started");

  while (true) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[CAM] Frame capture failed");
      res = ESP_FAIL;
    }

    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, sizeof(part_buf), _STREAM_PART, fb->len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }

    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
    }

    if (res != ESP_OK) break;

    // Yield to prevent watchdog reset on heavy streaming
    vTaskDelay(pdMS_TO_TICKS(10));
  }

  Serial.println("[CAM] Stream stopped");
  return res;
}

// ============================================================
// START HTTP SERVER
// ============================================================

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port      = 80;
  config.max_uri_handlers = 8;

  httpd_uri_t index_uri = {
    .uri     = "/",
    .method  = HTTP_GET,
    .handler = index_handler,
    .user_ctx = NULL
  };
  httpd_uri_t stream_uri = {
    .uri     = "/stream",
    .method  = HTTP_GET,
    .handler = stream_handler,
    .user_ctx = NULL
  };
  httpd_uri_t capture_uri = {
    .uri     = "/capture",
    .method  = HTTP_GET,
    .handler = capture_handler,
    .user_ctx = NULL
  };

  Serial.printf("[CAM] Starting HTTP server on port %d\n", config.server_port);
  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &index_uri);
    httpd_register_uri_handler(camera_httpd, &stream_uri);
    httpd_register_uri_handler(camera_httpd, &capture_uri);
    Serial.println("[CAM] HTTP server started OK");
  } else {
    Serial.println("[CAM] ERROR: HTTP server failed to start");
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  // Disable brownout detector (ESP32-CAM can brown-out on USB power)
  // Note: soc/soc.h and soc/rtc_cntl_reg.h are included at the top
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  Serial.setDebugOutput(false);
  Serial.println();
  Serial.println("==============================");
  Serial.println("     IKRU EYES STARTING");
  Serial.println("==============================");

  // --------------------------------------------------------
  // Camera Configuration
  // --------------------------------------------------------
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  // Arduino Core 3.x: pin_sda / pin_scl (replaces deprecated pin_sscb_sda/scl)
  config.pin_sda      = SIOD_GPIO_NUM;
  config.pin_scl      = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = CAMERA_RESOLUTION;
    config.jpeg_quality = CAMERA_JPEG_QUALITY;
    config.fb_count     = 2;
    config.grab_mode    = CAMERA_GRAB_LATEST;
    Serial.println("[CAM] PSRAM found — using dual framebuffer");
  } else {
    config.frame_size   = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count     = 1;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
    Serial.println("[CAM] No PSRAM — single framebuffer mode");
  }

  // --------------------------------------------------------
  // Initialize Camera
  // --------------------------------------------------------
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] INIT FAILED: 0x%x — check wiring and power\n", err);
    return;
  }
  Serial.println("[CAM] Camera initialized OK");

  // --------------------------------------------------------
  // Sensor Tuning (OV2640)
  // --------------------------------------------------------
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s,  0);    // -2 to 2
    s->set_contrast(s,    0);    // -2 to 2
    s->set_saturation(s,  0);    // -2 to 2
    s->set_whitebal(s,    1);    // AWB enable
    s->set_awb_gain(s,    1);    // AWB gain enable
    s->set_wb_mode(s,     0);    // 0=Auto
    s->set_exposure_ctrl(s, 1);  // AEC enable
    s->set_aec2(s,        1);    // DSP AEC enable
    s->set_gain_ctrl(s,   1);    // AGC enable
    s->set_bpc(s,         1);    // Black pixel correction
    s->set_wpc(s,         1);    // White pixel correction
    s->set_hmirror(s,     0);    // Mirror off
    s->set_vflip(s,       0);    // Flip off
    Serial.println("[CAM] Sensor tuning applied");
  }

  // --------------------------------------------------------
  // Wi-Fi Connection
  // --------------------------------------------------------
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  WiFi.setSleep(false);   // Disable WiFi power save for low-latency streaming

  Serial.printf("[WiFi] Connecting to %s", ssid);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WiFi] CONNECTION FAILED — check SSID/password");
    return;
  }

  Serial.println();
  Serial.println("[WiFi] Connected!");
  Serial.print("[WiFi] IP Address: http://");
  Serial.println(WiFi.localIP());

  // --------------------------------------------------------
  // Start HTTP Server
  // --------------------------------------------------------
  startCameraServer();

  Serial.println("==============================");
  Serial.println("       IKRU EYES READY");
  Serial.println("==============================");
}

void loop() {
  // HTTP server runs on FreeRTOS tasks in the background.
  // Keep loop alive with a watchdog-friendly delay.
  delay(1000);
}
