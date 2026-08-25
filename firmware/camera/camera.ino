#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiUdp.h>

// ============================================================
// IKRU ESP32-CAM
// AP MODE + UDP JPEG STREAM TEST
// ============================================================

// ---------------- Wi-Fi AP ----------------

const char* AP_SSID = "IKRU-CAM";
const char* AP_PASSWORD = "ikru@potato";

IPAddress AP_IP(192, 168, 4, 1);
IPAddress AP_GATEWAY(192, 168, 4, 1);
IPAddress AP_SUBNET(255, 255, 255, 0);

// ---------------- UDP ----------------

WiFiUDP udp;

const uint16_t LOCAL_PORT = 2223;
const uint16_t VIDEO_PORT = 2222;

// PC IP is learned through discovery.
IPAddress pcIP;

bool pcKnown = false;

// ============================================================
// CAMERA SETTINGS
// ============================================================

#define FRAME_SIZE   FRAMESIZE_QVGA
#define JPEG_QUALITY 20
#define FB_COUNT     2

// Keep below normal MTU.
#define CHUNK_SIZE   1200

// ============================================================
// AI-THINKER ESP32-CAM PINS
// ============================================================

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM        35
#define Y8_GPIO_NUM        34
#define Y7_GPIO_NUM        39
#define Y6_GPIO_NUM        36
#define Y5_GPIO_NUM        21
#define Y4_GPIO_NUM        19
#define Y3_GPIO_NUM        18
#define Y2_GPIO_NUM         5

#define VSYNC_GPIO_NUM     25
#define HREF_GPIO_NUM      23
#define PCLK_GPIO_NUM      22

// ============================================================
// PACKET HEADER
// ============================================================

#define MAGIC        0x494B
#define VERSION      1
#define PACKET_VIDEO 0

struct __attribute__((packed)) CameraPacketHeader {

  uint16_t magic;

  uint8_t version;
  uint8_t packetType;

  uint32_t frameId;

  uint16_t chunkId;
  uint16_t totalChunks;

  uint32_t frameLength;

  uint16_t chunkLength;

  uint32_t timestamp;

};

uint32_t frameId = 0;

// ============================================================
// CAMERA INITIALIZATION
// ============================================================

bool initCamera() {

  camera_config_t config;

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

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;

  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href  = HREF_GPIO_NUM;

  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn  = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;

  config.pixel_format = PIXFORMAT_JPEG;

  config.frame_size = FRAME_SIZE;
  config.jpeg_quality = JPEG_QUALITY;

  config.fb_count = FB_COUNT;

  config.grab_mode = CAMERA_GRAB_LATEST;

  if (psramFound()) {

    config.fb_location = CAMERA_FB_IN_PSRAM;

    Serial.println("[CAM] PSRAM detected");

  } else {

    config.fb_location = CAMERA_FB_IN_DRAM;

    Serial.println("[CAM] WARNING: PSRAM not detected");
  }

  esp_err_t err = esp_camera_init(&config);

  if (err != ESP_OK) {

    Serial.printf(
      "[CAM] Initialization failed: 0x%lx\n",
      (unsigned long)err
    );

    return false;
  }

  Serial.println("[CAM] Camera initialized");

  return true;
}

// ============================================================
// ACCESS POINT
// ============================================================

void startAP() {

  Serial.println();
  Serial.println("[WIFI] Starting AP...");

  WiFi.mode(WIFI_AP);

  // Disable Wi-Fi sleep for lower latency.
  WiFi.setSleep(false);

  if (!WiFi.softAPConfig(
        AP_IP,
        AP_GATEWAY,
        AP_SUBNET
      )) {

    Serial.println("[WIFI] AP configuration failed");

    return;
  }

  if (!WiFi.softAP(
        AP_SSID,
        AP_PASSWORD,
        1,
        false,
        4
      )) {

    Serial.println("[WIFI] AP start failed");

    return;
  }

  delay(500);

  Serial.println("[WIFI] AP started");

  Serial.print("[WIFI] SSID: ");
  Serial.println(AP_SSID);

  Serial.print("[WIFI] Password: ");
  Serial.println(AP_PASSWORD);

  Serial.print("[WIFI] IP: ");
  Serial.println(WiFi.softAPIP());
}

// ============================================================
// DISCOVERY
//
// PC sends:
//
//     "IKRU_DISCOVER"
//
// ESP32 replies:
//
//     "IKRU_CAMERA"
//
// The source IP of the packet becomes the PC destination.
// ============================================================

void checkDiscovery() {

  int packetSize = udp.parsePacket();

  if (packetSize <= 0) {
    return;
  }

  char buffer[64];

  int len = udp.read(
    buffer,
    sizeof(buffer) - 1
  );

  if (len <= 0) {
    return;
  }

  buffer[len] = '\0';

  String message(buffer);

  if (message == "IKRU_DISCOVER") {

    pcIP = udp.remoteIP();

    pcKnown = true;

    Serial.print("[UDP] PC discovered: ");
    Serial.println(pcIP);

    udp.beginPacket(
      pcIP,
      VIDEO_PORT
    );

    udp.write(
      (const uint8_t*)"IKRU_CAMERA",
      11
    );

    udp.endPacket();
  }
}

// ============================================================
// SEND ONE JPEG FRAME
// ============================================================

void sendFrame(camera_fb_t* fb) {

  if (!pcKnown || !fb) {
    return;
  }

  uint32_t frameLength = fb->len;

  uint16_t totalChunks =
    (frameLength + CHUNK_SIZE - 1) /
    CHUNK_SIZE;

  uint32_t currentFrame = frameId++;

  uint32_t timestamp = millis();

  for (
    uint16_t chunkId = 0;
    chunkId < totalChunks;
    chunkId++
  ) {

    uint32_t offset =
      (uint32_t)chunkId * CHUNK_SIZE;

    uint32_t remaining =
      frameLength - offset;

    uint16_t chunkLength =
      remaining > CHUNK_SIZE
        ? CHUNK_SIZE
        : (uint16_t)remaining;

    CameraPacketHeader header;

    header.magic = MAGIC;
    header.version = VERSION;
    header.packetType = PACKET_VIDEO;

    header.frameId = currentFrame;

    header.chunkId = chunkId;
    header.totalChunks = totalChunks;

    header.frameLength = frameLength;
    header.chunkLength = chunkLength;

    header.timestamp = timestamp;

    if (!udp.beginPacket(
          pcIP,
          VIDEO_PORT
        )) {

      return;
    }

    udp.write(
      (const uint8_t*)&header,
      sizeof(header)
    );

    udp.write(
      fb->buf + offset,
      chunkLength
    );

    if (!udp.endPacket()) {

      Serial.println(
        "[UDP] Packet send failed"
      );

      return;
    }
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("==========================================");
  Serial.println("       IKRU ESP32-CAM AP TEST");
  Serial.println("       UDP JPEG STREAM");
  Serial.println("==========================================");

  if (!initCamera()) {

    Serial.println(
      "[FATAL] Camera initialization failed"
    );

    while (true) {
      delay(1000);
    }
  }

  startAP();

  udp.begin(LOCAL_PORT);

  Serial.print(
    "[UDP] Listening for discovery on port: "
  );

  Serial.println(LOCAL_PORT);

  Serial.println();
  Serial.println(
    "[READY] Connect PC to IKRU-CAM"
  );

  Serial.println(
    "[READY] Waiting for PC discovery..."
  );
}

// ============================================================
// LOOP
// ============================================================

void loop() {

  // Check if PC has discovered us.

  checkDiscovery();

  // No PC yet.

  if (!pcKnown) {

    delay(5);

    return;
  }

  // Capture frame.

  camera_fb_t* fb =
    esp_camera_fb_get();

  if (!fb) {

    Serial.println(
      "[CAM] Frame capture failed"
    );

    delay(5);

    return;
  }

  sendFrame(fb);

  // IMPORTANT:
  // Return framebuffer only after ALL
  // packets referencing it were sent.

  esp_camera_fb_return(fb);

  delay(1);
}