#include <Arduino.h>
#include <WiFi.h>

// ============================================================
// IKRU ESP32-CAM WAV AUDIO PLAYER
//
// ESP32-CAM = Wi-Fi Access Point
// PC         = Wi-Fi Client
//
// PC sends WAV -> TCP -> ESP32 -> PCM -> PWM GPIO 2
// GPIO 2 -> SmartElex IN
// ============================================================

// ============================================================
// WIFI AP
// ============================================================

const char* AP_SSID = "esp_audio";
const char* AP_PASSWORD = "ikru@potato";

WiFiServer server(5000);

// ============================================================
// AUDIO
// ============================================================

#define AUDIO_PIN 2

#define PWM_FREQUENCY 20000
#define PWM_RESOLUTION 8

// ============================================================
// BUFFER
// ============================================================

#define AUDIO_BUFFER_SIZE 2048

uint8_t audioBuffer[AUDIO_BUFFER_SIZE];

// ============================================================
// WAV INFORMATION
// ============================================================

uint16_t wavChannels = 0;
uint16_t wavBits = 0;
uint32_t wavSampleRate = 0;
uint32_t wavDataSize = 0;

// ============================================================
// READ EXACT BYTES
// ============================================================

bool readExact(
    WiFiClient& client,
    uint8_t* buffer,
    size_t length
) {

    size_t received = 0;

    unsigned long lastData = millis();

    while (received < length) {

        if (!client.connected()) {
            return false;
        }

        int available = client.available();

        if (available > 0) {

            int n = client.read(
                buffer + received,
                length - received
            );

            if (n > 0) {

                received += n;
                lastData = millis();
            }

        } else {

            if (millis() - lastData > 5000) {
                return false;
            }

            delay(1);
        }
    }

    return true;
}

// ============================================================
// LITTLE-ENDIAN READERS
// ============================================================

uint16_t read16(
    const uint8_t* p
) {

    return
        (uint16_t)p[0] |
        ((uint16_t)p[1] << 8);
}

uint32_t read32(
    const uint8_t* p
) {

    return
        (uint32_t)p[0] |
        ((uint32_t)p[1] << 8) |
        ((uint32_t)p[2] << 16) |
        ((uint32_t)p[3] << 24);
}

// ============================================================
// WAIT UNTIL SAMPLE TIME
// ============================================================

inline void waitForSample(
    uint32_t& nextSampleTime,
    uint32_t samplePeriodUs
) {

    nextSampleTime += samplePeriodUs;

    while (
        (int32_t)(
            micros() -
            nextSampleTime
        ) < 0
    ) {
        // Busy wait for precise timing.
    }
}

// ============================================================
// PLAY MONO 8-BIT PCM
// ============================================================

void playMono8(
    WiFiClient& client,
    uint32_t dataSize,
    uint32_t sampleRate
) {

    uint32_t remaining = dataSize;

    uint32_t samplePeriodUs =
        1000000UL / sampleRate;

    uint32_t nextSampleTime =
        micros();

    Serial.println(
        "[AUDIO] Playing 8-bit mono..."
    );

    while (
        remaining > 0 &&
        client.connected()
    ) {

        size_t amount =
            min(
                (uint32_t)AUDIO_BUFFER_SIZE,
                remaining
            );

        if (!readExact(
                client,
                audioBuffer,
                amount
            )) {

            Serial.println(
                "[AUDIO] Connection lost"
            );

            return;
        }

        for (
            size_t i = 0;
            i < amount;
            i++
        ) {

            // WAV 8-bit PCM is unsigned:
            //
            // 0   = minimum
            // 128 = center
            // 255 = maximum
            //
            // Perfectly matches 8-bit PWM.

            ledcWrite(
                AUDIO_PIN,
                audioBuffer[i]
            );

            waitForSample(
                nextSampleTime,
                samplePeriodUs
            );
        }

        remaining -= amount;
    }

    ledcWrite(
        AUDIO_PIN,
        128
    );
}

// ============================================================
// PLAY MONO 16-BIT PCM
// ============================================================

void playMono16(
    WiFiClient& client,
    uint32_t dataSize,
    uint32_t sampleRate
) {

    uint32_t remaining = dataSize;

    uint32_t samplePeriodUs =
        1000000UL / sampleRate;

    uint32_t nextSampleTime =
        micros();

    Serial.println(
        "[AUDIO] Playing 16-bit mono..."
    );

    while (
        remaining >= 2 &&
        client.connected()
    ) {

        size_t amount =
            min(
                (uint32_t)AUDIO_BUFFER_SIZE,
                remaining
            );

        // Always read an even number
        // of bytes for 16-bit samples.

        amount &= ~1;

        if (!readExact(
                client,
                audioBuffer,
                amount
            )) {

            Serial.println(
                "[AUDIO] Connection lost"
            );

            return;
        }

        for (
            size_t i = 0;
            i < amount;
            i += 2
        ) {

            int16_t sample =
                (int16_t)(
                    (uint16_t)audioBuffer[i] |
                    ((uint16_t)audioBuffer[i + 1] << 8)
                );

            // ------------------------------------------------
            // Convert:
            //
            // 16-bit signed
            // -32768 ... +32767
            //
            // to:
            //
            // 8-bit unsigned PWM
            // 0 ... 255
            // ------------------------------------------------

            int pwm =
                (sample >> 8) + 128;

            pwm =
                constrain(
                    pwm,
                    0,
                    255
                );

            ledcWrite(
                AUDIO_PIN,
                pwm
            );

            waitForSample(
                nextSampleTime,
                samplePeriodUs
            );
        }

        remaining -= amount;
    }

    ledcWrite(
        AUDIO_PIN,
        128
    );
}

// ============================================================
// PLAY STEREO 16-BIT PCM
// ============================================================

void playStereo16(
    WiFiClient& client,
    uint32_t dataSize,
    uint32_t sampleRate
) {

    uint32_t remaining = dataSize;

    uint32_t samplePeriodUs =
        1000000UL / sampleRate;

    uint32_t nextSampleTime =
        micros();

    Serial.println(
        "[AUDIO] Playing 16-bit stereo..."
    );

    while (
        remaining >= 4 &&
        client.connected()
    ) {

        size_t amount =
            min(
                (uint32_t)AUDIO_BUFFER_SIZE,
                remaining
            );

        // Each stereo sample = 4 bytes.

        amount -= amount % 4;

        if (!readExact(
                client,
                audioBuffer,
                amount
            )) {

            Serial.println(
                "[AUDIO] Connection lost"
            );

            return;
        }

        for (
            size_t i = 0;
            i < amount;
            i += 4
        ) {

            int16_t left =
                (int16_t)(
                    (uint16_t)audioBuffer[i] |
                    ((uint16_t)audioBuffer[i + 1] << 8)
                );

            int16_t right =
                (int16_t)(
                    (uint16_t)audioBuffer[i + 2] |
                    ((uint16_t)audioBuffer[i + 3] << 8)
                );

            // Stereo -> mono

            int32_t mono =
                ((int32_t)left +
                 (int32_t)right) / 2;

            int pwm =
                (mono >> 8) + 128;

            pwm =
                constrain(
                    pwm,
                    0,
                    255
                );

            ledcWrite(
                AUDIO_PIN,
                pwm
            );

            waitForSample(
                nextSampleTime,
                samplePeriodUs
            );
        }

        remaining -= amount;
    }

    ledcWrite(
        AUDIO_PIN,
        128
    );
}

// ============================================================
// PARSE WAV
// ============================================================

bool parseWav(
    uint8_t* header
) {

    // --------------------------------------------------------
    // RIFF
    // --------------------------------------------------------

    if (
        header[0] != 'R' ||
        header[1] != 'I' ||
        header[2] != 'F' ||
        header[3] != 'F'
    ) {

        Serial.println(
            "[AUDIO] ERROR: Missing RIFF"
        );

        return false;
    }

    // --------------------------------------------------------
    // WAVE
    // --------------------------------------------------------

    if (
        header[8] != 'W' ||
        header[9] != 'A' ||
        header[10] != 'V' ||
        header[11] != 'E'
    ) {

        Serial.println(
            "[AUDIO] ERROR: Missing WAVE"
        );

        return false;
    }

    uint16_t audioFormat =
        read16(&header[20]);

    wavChannels =
        read16(&header[22]);

    wavSampleRate =
        read32(&header[24]);

    wavBits =
        read16(&header[34]);

    wavDataSize =
        read32(&header[40]);

    Serial.println();
    Serial.println(
        "================================"
    );

    Serial.println(
        "         WAV INFORMATION"
    );

    Serial.println(
        "================================"
    );

    Serial.printf(
        "Format       : %u\n",
        audioFormat
    );

    Serial.printf(
        "Channels     : %u\n",
        wavChannels
    );

    Serial.printf(
        "Sample rate  : %lu Hz\n",
        (unsigned long)wavSampleRate
    );

    Serial.printf(
        "Bits/sample  : %u\n",
        wavBits
    );

    Serial.printf(
        "Audio bytes  : %lu\n",
        (unsigned long)wavDataSize
    );

    Serial.println(
        "================================"
    );

    // PCM only

    if (audioFormat != 1) {

        Serial.println(
            "[AUDIO] ERROR: Not PCM WAV"
        );

        return false;
    }

    if (
        wavChannels != 1 &&
        wavChannels != 2
    ) {

        Serial.println(
            "[AUDIO] ERROR: "
            "Only mono/stereo supported"
        );

        return false;
    }

    if (
        wavBits != 8 &&
        wavBits != 16
    ) {

        Serial.println(
            "[AUDIO] ERROR: "
            "Only 8/16-bit PCM supported"
        );

        return false;
    }

    return true;
}

// ============================================================
// PLAY WAV
// ============================================================

void playWav(
    WiFiClient& client
) {

    uint8_t header[44];

    if (!readExact(
            client,
            header,
            44
        )) {

        Serial.println(
            "[AUDIO] Failed to receive WAV header"
        );

        return;
    }

    if (!parseWav(header)) {
        return;
    }

    // --------------------------------------------------------
    // Configure PWM
    // --------------------------------------------------------

    uint32_t sampleRate =
        wavSampleRate;

    // --------------------------------------------------------
    // Playback
    // --------------------------------------------------------

    if (
        wavBits == 8 &&
        wavChannels == 1
    ) {

        playMono8(
            client,
            wavDataSize,
            sampleRate
        );

    } else if (
        wavBits == 16 &&
        wavChannels == 1
    ) {

        playMono16(
            client,
            wavDataSize,
            sampleRate
        );

    } else if (
        wavBits == 16 &&
        wavChannels == 2
    ) {

        playStereo16(
            client,
            wavDataSize,
            sampleRate
        );

    } else {

        Serial.println(
            "[AUDIO] Unsupported format"
        );

        return;
    }

    ledcWrite(
        AUDIO_PIN,
        128
    );

    Serial.println(
        "[AUDIO] Playback finished"
    );
}

// ============================================================
// SETUP
// ============================================================

void setup() {

    Serial.begin(115200);

    delay(1000);

    Serial.println();
    Serial.println(
        "=========================================="
    );

    Serial.println(
        "       IKRU ESP32-CAM AUDIO"
    );

    Serial.println(
        "       WAV -> PWM -> SMART ELEX"
    );

    Serial.println(
        "=========================================="
    );

    // --------------------------------------------------------
    // PWM
    // --------------------------------------------------------

    bool attached =
        ledcAttach(
            AUDIO_PIN,
            PWM_FREQUENCY,
            PWM_RESOLUTION
        );

    if (!attached) {

        Serial.println(
            "[ERROR] LEDC attach failed"
        );

        while (true) {
            delay(1000);
        }
    }

    ledcWrite(
        AUDIO_PIN,
        128
    );

    Serial.println(
        "[AUDIO] PWM ready"
    );

    // --------------------------------------------------------
    // Wi-Fi AP
    // --------------------------------------------------------

    WiFi.mode(
        WIFI_AP
    );

    WiFi.setSleep(
        false
    );

    WiFi.softAP(
        AP_SSID,
        AP_PASSWORD
    );

    delay(500);

    Serial.println(
        "[WIFI] Access Point started"
    );

    Serial.print(
        "[WIFI] SSID: "
    );

    Serial.println(
        AP_SSID
    );

    Serial.print(
        "[WIFI] Password: "
    );

    Serial.println(
        AP_PASSWORD
    );

    Serial.print(
        "[WIFI] IP: "
    );

    Serial.println(
        WiFi.softAPIP()
    );

    // --------------------------------------------------------
    // TCP SERVER
    // --------------------------------------------------------

    server.begin();

    Serial.println(
        "[SERVER] TCP port: 5000"
    );

    Serial.println(
        "[READY] Connect PC and send WAV"
    );
}

// ============================================================
// LOOP
// ============================================================

void loop() {

    WiFiClient client =
        server.available();

    if (!client) {

        delay(5);

        return;
    }

    Serial.println();
    Serial.println(
        "[SERVER] PC connected"
    );

    client.setTimeout(5000);

    playWav(client);

    client.stop();

    Serial.println(
        "[SERVER] PC disconnected"
    );
}