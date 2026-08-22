#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ============================================================
// IKRU EYES — ESP32-CAM FIRMWARE
//
// Hardware:
// AI-Thinker ESP32-CAM Module
// OV2640 Camera
//
// Functionality:
// Connects to WiFi, hosts an HTTP Web Server on port 80.
// Serves live MJPEG video stream at `/stream`, snapshots at `/capture`,
// and an index page at `/` with a premium dark theme.
// ============================================================

// ============================================================
// CONFIGURATION
// ============================================================

// Wi-Fi Credentials
const char *ssid = "GNXS-2.4G-C457E1";
const char *password = "1234567890";

// Camera Parameters
#define CAMERA_RESOLUTION FRAMESIZE_QVGA  // Options: FRAMESIZE_QVGA (320x240), FRAMESIZE_CIF (400x296), FRAMESIZE_VGA (640x480)
#define CAMERA_JPEG_QUALITY 12             // 10-63 (lower means higher quality, larger size)

// ============================================================
// AI-THINKER CAMERA PINS
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
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// ============================================================
// HTTP HANDLERS
// ============================================================

// 1. HTML INDEX PAGE (Catppuccin Dark Theme)
esp_err_t index_handler(httpd_req_t *req) {
  httpd_resp_set_type(req, "text/html");
  String html = "<html><head><title>IKRU Eyes - Live Feed</title><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>"
                "body { font-family: 'Segoe UI', Arial, sans-serif; background-color: #1e1e2e; color: #cdd6f4; text-align: center; margin: 0; padding: 20px; }"
                "h1 { color: #f5c2e7; margin-bottom: 5px; font-weight: 600; }"
                "h3 { color: #a6adc8; font-weight: 400; margin-top: 0; margin-bottom: 25px; }"
                ".container { max-width: 650px; margin: auto; background-color: #313244; padding: 30px; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); border: 1px solid #45475a; }"
                ".stream-box { position: relative; display: inline-block; background-color: #11111b; padding: 10px; border-radius: 12px; border: 2px solid #b4befe; box-shadow: inset 0 0 10px rgba(0,0,0,0.8); }"
                "img { display: block; border-radius: 8px; max-width: 100%; height: auto; }"
                ".info { margin-top: 25px; font-size: 14px; color: #bac2de; text-align: left; background-color: #181825; padding: 15px; border-radius: 8px; border: 1px solid #45475a; }"
                "p { margin: 6px 0; }"
                "code { background-color: #313244; color: #f9e2af; padding: 2px 6px; border-radius: 4px; font-family: Consolas, monospace; }"
                "a { color: #89b4fa; text-decoration: none; font-weight: bold; transition: color 0.2s; }"
                "a:hover { color: #94e2d5; }"
                "</style></head><body>"
                "<div class='container'>"
                "<h1>🤖 IKRU Eyes</h1>"
                "<h3>Network Camera Stream</h3>"
                "<div class='stream-box'>"
                "<img src='/stream' />"
                "</div>"
                "<div class='info'>"
                "<p><strong>MJPEG Stream URL:</strong> <code>http://" + WiFi.localIP().toString() + "/stream</code> (Direct link: <a href='/stream' target='_blank'>Stream</a>)</p>"
                "<p><strong>JPEG Snapshot URL:</strong> <code>http://" + WiFi.localIP().toString() + "/capture</code> (Direct link: <a href='/capture' target='_blank'>Capture</a>)</p>"
                "<p><strong>Wi-Fi Network:</strong> <code>" + String(ssid) + "</code></p>"
                "<p><strong>Signal Strength (RSSI):</strong> <code>" + String(WiFi.RSSI()) + " dBm</code></p>"
                "</div></div></body></html>";
  return httpd_resp_send(req, html.c_str(), html.length());
}

// 2. JPEG SNAPSHOT HANDLER
esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;

  // Flush frame buffer to ensure latest image
  fb = esp_camera_fb_get();
  if (fb) {
    esp_camera_fb_return(fb);
  }

  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  res = httpd_resp_set_type(req, "image/jpeg");
  if (res == ESP_OK) {
    res = httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  }
  if (res == ESP_OK) {
    res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  }

  esp_camera_fb_return(fb);
  return res;
}

// 3. LIVE MJPEG STREAM HANDLER (Low Latency)
esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t *_jpg_buf = NULL;
  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if (res != ESP_OK) {
    return res;
  }

  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  Serial.println("Stream started");

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }

    if (res == ESP_OK) {
      size_t hlen = snprintf(part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }

    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    }

    if (res != ESP_OK) {
      break;
    }
  }

  Serial.println("Stream stopped");
  return res;
}

// ============================================================
// START HTTP SERVER
// ============================================================

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;

  // Set URI handlers
  httpd_uri_t index_uri = {
    .uri      = "/",
    .method   = HTTP_GET,
    .handler  = index_handler,
    .user_ctx = NULL
  };

  httpd_uri_t stream_uri = {
    .uri      = "/stream",
    .method   = HTTP_GET,
    .handler  = stream_handler,
    .user_ctx = NULL
  };

  httpd_uri_t capture_uri = {
    .uri      = "/capture",
    .method   = HTTP_GET,
    .handler  = capture_handler,
    .user_ctx = NULL
  };

  Serial.print("Starting HTTP server on port: '");
  Serial.print(config.server_port);
  Serial.println("'");

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &index_uri);
    httpd_register_uri_handler(camera_httpd, &stream_uri);
    httpd_register_uri_handler(camera_httpd, &capture_uri);
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  // Disable brownout detector if power lines are noisy
  #include "soc/soc.h"
  #include "soc/rtc_cntl_reg.h"
  WRITE_PERI_REG(RTC_CNTL_BROWNOUT_REG, 0);

  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("==============================");
  Serial.println("    IKRU EYES STARTING");
  Serial.println("==============================");

  // Camera settings
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // Check PSRAM
  if (psramFound()) {
    config.frame_size = CAMERA_RESOLUTION;
    config.jpeg_quality = CAMERA_JPEG_QUALITY;
    config.fb_count = 2;
    // Set grab mode to latest if available to minimize latency
    #ifdef CAMERA_GRAB_LATEST
    config.grab_mode = CAMERA_GRAB_LATEST;
    #endif
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  // Camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }

  // Configure camera settings (exposure, gain, saturation, contrast)
  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    // Initial optimizations for OV2640 sensor
    s->set_brightness(s, 0);     // -2 to 2
    s->set_contrast(s, 0);       // -2 to 2
    s->set_saturation(s, 0);     // -2 to 2
    s->set_whitebal(s, 1);       // 0 = disable , 1 = enable
    s->set_awb_gain(s, 1);       // 0 = disable , 1 = enable
    s->set_wb_mode(s, 0);        // 0 to 4 (0: Auto, 1: Sunny, 2: Cloudy, 3: Office, 4: Home)
    s->set_exposure_control(s, 1); // 0 = disable , 1 = enable
    s->set_aec2(s, 1);           // 0 = disable , 1 = enable
    s->set_gain_control(s, 1);   // 0 = disable , 1 = enable
    s->set_bpc(s, 1);            // Black pixel correction (0/1)
    s->set_wpc(s, 1);            // White pixel correction (0/1)
    s->set_hmirror(s, 0);        // Horizontal mirror (0/1)
    s->set_vflip(s, 0);          // Vertical flip (0/1)
  }

  // Connect to Wi-Fi
  Serial.printf("Connecting to Wi-Fi SSID: %s\n", ssid);
  WiFi.begin(ssid, password);

  // Disable Wi-Fi sleep for low-latency transmission
  WiFi.setSleep(false);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("Wi-Fi connected!");
  Serial.print("Local IP Address: http://");
  Serial.println(WiFi.localIP());

  // Start HTTP Camera Server
  startCameraServer();
}

void loop() {
  // Web server runs in the background. Nothing needed here.
  delay(1000);
}
