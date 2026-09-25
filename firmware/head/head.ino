#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_netif.h"
#include "dhcpserver/dhcpserver.h"

// =============================================================================
// PROJECT IKRU — HEAD UNIT (VISION STREAMER)
// Hardware: AI-Thinker ESP32-CAM + OV2640 Camera
//
// Capabilities:
// 1. Wi-Fi Access Point ('IKRU-CAM' @ 192.168.4.1)
// 2. High-speed UDP Video JPEG Streaming (Port 2222) + Discovery Handshake (Port 2223)
// =============================================================================

// ---------------- Wi-Fi AP ----------------
const char* AP_SSID = "IKRU-CAM";
const char* AP_PASSWORD = "ikru@potato";

const IPAddress AP_IP(192, 168, 4, 1);
const IPAddress AP_GATEWAY(192, 168, 4, 1);
const IPAddress AP_SUBNET(255, 255, 255, 0);

// ---------------- UDP Video & Discovery ----------------
WiFiUDP udp;
const uint16_t DISCOVERY_PORT = 2223;
const uint16_t VIDEO_PORT = 2222;

IPAddress pcIP;
bool pcKnown = false;

// =============================================================================
// CAMERA SETTINGS & AI-THINKER PIN MAP
// =============================================================================
#define FRAME_SIZE   FRAMESIZE_QVGA
#define JPEG_QUALITY 20
#define FB_COUNT     2
#define CHUNK_SIZE   1200

// Camera Orientation Settings (OV2640)
#define CAMERA_VFLIP    1  // 1 = Flip vertically (fixes upside-down camera casting)
#define CAMERA_HMIRROR  0  // 1 = Mirror horizontally (set to 1 if left-to-right is also mirrored)

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

// =============================================================================
// VIDEO PACKET PROTOCOL
// =============================================================================
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

// =============================================================================
// CAMERA INITIALIZATION & UDP STREAMING
// =============================================================================
bool initCamera() {
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
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;

    if (psramFound()) {
        config.frame_size   = FRAME_SIZE;
        config.jpeg_quality = JPEG_QUALITY;
        config.fb_count     = FB_COUNT;
    } else {
        config.frame_size   = FRAMESIZE_QVGA;
        config.jpeg_quality = 12;
        config.fb_count     = 1;
    }

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        return false;
    }

    // Correct image orientation via sensor registers
    sensor_t* s = esp_camera_sensor_get();
    if (s != NULL) {
        s->set_vflip(s, CAMERA_VFLIP);
        s->set_hmirror(s, CAMERA_HMIRROR);
    }

    return true;
}

// IKRU-CAM has no internet. If its DHCP server offers a gateway, a PC on two
// Wi-Fi adapters (home + IKRU-CAM) may route internet traffic here and go offline.
// Offering no router keeps the PC's internet on home Wi-Fi.
void disableGatewayOffer() {
    esp_netif_t* ap = WiFi.AP.netif();
    if (!ap) return;
    dhcps_offer_t offer = 0;  // clears OFFER_ROUTER
    esp_netif_dhcps_stop(ap);
    esp_err_t err = esp_netif_dhcps_option(ap, ESP_NETIF_OP_SET, ESP_NETIF_ROUTER_SOLICITATION_ADDRESS,
                                           &offer, sizeof(offer));
    esp_netif_dhcps_start(ap);
    Serial.printf("[WIFI] DHCP gateway offer disabled: %s\n", err == ESP_OK ? "yes" : esp_err_to_name(err));
}

void startAP() {
    WiFi.mode(WIFI_AP);
    WiFi.setSleep(false);
    WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
    disableGatewayOffer();

    Serial.println("[WIFI] Head AP Started!");
    Serial.printf("  SSID     : %s\n", AP_SSID);
    Serial.printf("  Password : %s\n", AP_PASSWORD);
    Serial.printf("  IP       : %s\n", WiFi.softAPIP().toString().c_str());
}

void checkDiscovery() {
    int packetSize = udp.parsePacket();
    if (!packetSize) return;

    char buffer[64];
    int len = udp.read(buffer, sizeof(buffer) - 1);
    if (len <= 0) return;
    buffer[len] = '\0';

    String msg(buffer);
    msg.trim();

    if (msg == "IKRU_DISCOVER" || msg == "DISCOVER_IKRU_CAM" || msg.indexOf("DISCOVER") >= 0) {
        pcIP = udp.remoteIP();
        pcKnown = true;

        // ACK on discovery port
        udp.beginPacket(pcIP, DISCOVERY_PORT);
        udp.write((const uint8_t*)"IKRU_CAM_ACK", 12);
        udp.endPacket();

        // ACK on video port
        udp.beginPacket(pcIP, VIDEO_PORT);
        udp.write((const uint8_t*)"IKRU_CAMERA", 11);
        udp.endPacket();

        Serial.printf("[DISCOVERY] PC Connected: %s\n", pcIP.toString().c_str());
    }
}

void sendFrame(camera_fb_t* fb) {
    if (!pcKnown || !fb) return;

    frameId++;
    uint32_t totalLength = fb->len;
    uint16_t totalChunks = (totalLength + CHUNK_SIZE - 1) / CHUNK_SIZE;
    uint32_t ts = millis();

    for (uint16_t chunkId = 0; chunkId < totalChunks; chunkId++) {
        uint32_t offset = chunkId * CHUNK_SIZE;
        uint16_t currentChunkLength = (chunkId == totalChunks - 1) ? (totalLength - offset) : CHUNK_SIZE;

        CameraPacketHeader header;
        header.magic       = MAGIC;
        header.version     = VERSION;
        header.packetType  = PACKET_VIDEO;
        header.frameId     = frameId;
        header.chunkId     = chunkId;
        header.totalChunks = totalChunks;
        header.frameLength = totalLength;
        header.chunkLength = currentChunkLength;
        header.timestamp   = ts;

        if (!udp.beginPacket(pcIP, VIDEO_PORT)) return;
        udp.write((const uint8_t*)&header, sizeof(CameraPacketHeader));
        udp.write(fb->buf + offset, currentChunkLength);
        if (!udp.endPacket()) return;
    }
}

// =============================================================================
// SETUP & LOOP
// =============================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("   PROJECT IKRU — HEAD UNIT FIRMWARE      ");
    Serial.println("   OV2640 Vision Streaming                ");
    Serial.println("==========================================");

    // 1. Initialize Camera (LEDC Channel 0 for XCLK 20MHz)
    if (!initCamera()) {
        Serial.println("[FATAL] Camera init failed!");
        while (true) delay(1000);
    }
    Serial.println("[CAM] Camera initialized successfully.");

    // 2. Start AP & UDP Discovery
    startAP();
    udp.begin(DISCOVERY_PORT);

    Serial.println("[READY] Video on UDP 2222 | Discovery on 2223");
}

void loop() {
    // 1. Poll UDP discovery
    checkDiscovery();

    // 2. Stream video frame if PC is connected
    if (pcKnown) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb) {
            sendFrame(fb);
            esp_camera_fb_return(fb);
        }
    }

    delay(1);
}