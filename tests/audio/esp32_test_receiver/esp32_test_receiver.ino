#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "ESP_I2S.h"

// =====================================================
// WiFi
// =====================================================

const char* WIFI_SSID = "GNXS-2.4G-C457E1";
const char* WIFI_PASSWORD = "1234567890";

const char* AUDIO_URL =
    "http://192.168.1.33:8000/test.wav";

// =====================================================
// MAX98357A / I2S
// =====================================================

I2SClass I2S;

#define I2S_WS    25
#define I2S_BCLK  26
#define I2S_DOUT  27

#define SAMPLE_RATE 44100

// =====================================================
// Streaming buffer
// =====================================================

#define BUFFER_SIZE 16384

uint8_t audioBuffer[BUFFER_SIZE];


// =====================================================
// Little-endian helpers
// =====================================================

uint16_t readLE16(uint8_t* p)
{
    return ((uint16_t)p[0]) |
           ((uint16_t)p[1] << 8);
}

uint32_t readLE32(uint8_t* p)
{
    return ((uint32_t)p[0]) |
           ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}


// =====================================================
// Read exactly N bytes
// =====================================================

bool readExact(
    WiFiClient& stream,
    uint8_t* buffer,
    size_t length
)
{
    size_t received = 0;

    while (received < length)
    {
        if (stream.available())
        {
            int n = stream.read(
                buffer + received,
                length - received
            );

            if (n > 0)
            {
                received += n;
            }
        }
        else
        {
            if (!stream.connected())
            {
                return false;
            }

            delay(1);
        }
    }

    return true;
}


// =====================================================
// Skip bytes
// =====================================================

bool skipBytes(
    WiFiClient& stream,
    uint32_t length
)
{
    uint8_t temp[64];

    while (length > 0)
    {
        size_t amount = min(
            length,
            (uint32_t)sizeof(temp)
        );

        if (!readExact(
                stream,
                temp,
                amount
            ))
        {
            return false;
        }

        length -= amount;
    }

    return true;
}


// =====================================================
// Parse WAV header
// =====================================================

bool findWavData(
    WiFiClient& stream,
    uint32_t& dataSize
)
{
    uint8_t header[12];

    if (!readExact(
            stream,
            header,
            12
        ))
    {
        Serial.println(
            "ERROR: Cannot read WAV header"
        );

        return false;
    }


    // RIFF
    if (memcmp(
            header,
            "RIFF",
            4
        ) != 0)
    {
        Serial.println(
            "ERROR: Not a RIFF file"
        );

        return false;
    }


    // WAVE
    if (memcmp(
            header + 8,
            "WAVE",
            4
        ) != 0)
    {
        Serial.println(
            "ERROR: Not a WAVE file"
        );

        return false;
    }


    bool foundFmt = false;


    while (stream.connected())
    {
        uint8_t chunkHeader[8];

        if (!readExact(
                stream,
                chunkHeader,
                8
            ))
        {
            return false;
        }


        uint32_t chunkSize =
            readLE32(chunkHeader + 4);


        // =================================================
        // fmt
        // =================================================

        if (memcmp(
                chunkHeader,
                "fmt ",
                4
            ) == 0)
        {
            uint8_t fmt[16];

            if (!readExact(
                    stream,
                    fmt,
                    16
                ))
            {
                return false;
            }


            uint16_t format =
                readLE16(fmt);

            uint16_t channels =
                readLE16(fmt + 2);

            uint32_t sampleRate =
                readLE32(fmt + 4);

            uint16_t bits =
                readLE16(fmt + 14);


            Serial.println();
            Serial.println(
                "========================"
            );

            Serial.println(
                "WAV FORMAT"
            );

            Serial.println(
                "========================"
            );

            Serial.printf(
                "Format      : %u\n",
                format
            );

            Serial.printf(
                "Channels    : %u\n",
                channels
            );

            Serial.printf(
                "Sample rate : %lu Hz\n",
                sampleRate
            );

            Serial.printf(
                "Bit depth   : %u\n",
                bits
            );


            // PCM
            if (format != 1)
            {
                Serial.println(
                    "ERROR: WAV is not PCM"
                );

                return false;
            }


            // Stereo
            if (channels != 2)
            {
                Serial.println(
                    "ERROR: Expected stereo WAV"
                );

                return false;
            }


            // 44.1 kHz
            if (sampleRate != 44100)
            {
                Serial.println(
                    "ERROR: Expected 44100 Hz"
                );

                return false;
            }


            // 16-bit
            if (bits != 16)
            {
                Serial.println(
                    "ERROR: Expected 16-bit"
                );

                return false;
            }


            // Skip additional fmt data
            if (chunkSize > 16)
            {
                if (!skipBytes(
                        stream,
                        chunkSize - 16
                    ))
                {
                    return false;
                }
            }


            foundFmt = true;
        }


        // =================================================
        // data
        // =================================================

        else if (memcmp(
                    chunkHeader,
                    "data",
                    4
                ) == 0)
        {
            dataSize =
                readLE32(chunkHeader + 4);


            Serial.printf(
                "Audio data: %lu bytes\n",
                dataSize
            );


            return foundFmt;
        }


        // =================================================
        // Unknown chunk
        // =================================================

        else
        {
            Serial.printf(
                "Skipping chunk %.4s (%lu bytes)\n",
                chunkHeader,
                chunkSize
            );


            if (!skipBytes(
                    stream,
                    chunkSize
                ))
            {
                return false;
            }
        }
    }


    return false;
}


// =====================================================
// Connect WiFi
// =====================================================

void connectWiFi()
{
    Serial.println();
    Serial.println(
        "Connecting to WiFi..."
    );


    WiFi.begin(
        WIFI_SSID,
        WIFI_PASSWORD
    );


    while (
        WiFi.status() != WL_CONNECTED
    )
    {
        delay(500);

        Serial.print(".");
    }


    Serial.println();

    Serial.println(
        "WiFi connected!"
    );


    Serial.print(
        "ESP32 IP: "
    );

    Serial.println(
        WiFi.localIP()
    );


    Serial.print(
        "Signal strength: "
    );

    Serial.print(
        WiFi.RSSI()
    );

    Serial.println(
        " dBm"
    );
}


// =====================================================
// Play WAV
// =====================================================

void playWAV()
{
    HTTPClient http;


    Serial.println();
    Serial.println(
        "Connecting to audio server..."
    );


    http.begin(AUDIO_URL);


    int httpCode =
        http.GET();


    if (httpCode != HTTP_CODE_OK)
    {
        Serial.printf(
            "HTTP ERROR: %d\n",
            httpCode
        );

        http.end();

        return;
    }


    Serial.println(
        "Audio stream connected!"
    );


    WiFiClient* stream =
        http.getStreamPtr();


    uint32_t dataSize = 0;


    // ---------------------------------------------------
    // Parse WAV
    // ---------------------------------------------------

    if (!findWavData(
            *stream,
            dataSize
        ))
    {
        Serial.println(
            "ERROR: WAV parsing failed"
        );

        http.end();

        return;
    }


    Serial.println();
    Serial.println(
        "========================"
    );

    Serial.println(
        "PLAYING"
    );

    Serial.println(
        "========================"
    );


    uint32_t remaining =
        dataSize;


    uint32_t lastPrint = millis();


    // ---------------------------------------------------
    // Stream audio
    // ---------------------------------------------------

    while (
        remaining > 0 &&
        stream->connected()
    )
    {
        size_t toRead =
            min(
                (uint32_t)BUFFER_SIZE,
                remaining
            );


        // Stereo 16-bit:
        // 4 bytes per audio frame

        toRead -=
            toRead % 4;


        size_t bytesRead = 0;


        // ------------------------------------------------
        // Fill buffer
        // ------------------------------------------------

        while (
            bytesRead < toRead
        )
        {
            if (stream->available())
            {
                int n =
                    stream->read(
                        audioBuffer + bytesRead,
                        toRead - bytesRead
                    );


                if (n > 0)
                {
                    bytesRead += n;
                }
            }
            else
            {
                if (!stream->connected())
                {
                    break;
                }

                delay(1);
            }
        }


        if (bytesRead == 0)
        {
            break;
        }


        // ------------------------------------------------
        // Send PCM directly to I2S
        // ------------------------------------------------

        size_t written =
            I2S.write(
                audioBuffer,
                bytesRead
            );


        if (written == 0)
        {
            Serial.println(
                "WARNING: I2S write failed"
            );
        }


        remaining -= bytesRead;


        // ------------------------------------------------
        // Progress
        // ------------------------------------------------

        if (
            millis() - lastPrint > 1000
        )
        {
            uint32_t played =
                dataSize - remaining;


            float percent =
                ((float)played /
                 (float)dataSize) *
                100.0;


            Serial.printf(
                "Playback: %.1f%%\n",
                percent
            );


            lastPrint =
                millis();
        }
    }


    Serial.println();

    Serial.println(
        "PLAYBACK FINISHED"
    );


    http.end();
}


// =====================================================
// Setup
// =====================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);


    Serial.println();
    Serial.println(
        "======================================"
    );

    Serial.println(
        "ESP32 WiFi → I2S → MAX98357A"
    );

    Serial.println(
        "======================================"
    );


    // =================================================
    // WiFi
    // =================================================

    connectWiFi();


    // =================================================
    // I2S
    // =================================================

    Serial.println();

    Serial.println(
        "Starting I2S..."
    );


    I2S.setPins(
        I2S_BCLK,
        I2S_WS,
        I2S_DOUT
    );


    if (!I2S.begin(
            I2S_MODE_STD,
            SAMPLE_RATE,
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_STEREO
        ))
    {
        Serial.println(
            "I2S FAILED!"
        );


        while (true)
        {
            delay(1000);
        }
    }


    Serial.println(
        "I2S OK"
    );


    Serial.println();
    Serial.println(
        "Ready to stream audio!"
    );
}


// =====================================================
// Loop
// =====================================================

void loop()
{
    playWAV();


    Serial.println();

    Serial.println(
        "Song ended."
    );

    Serial.println(
        "Restarting in 2 seconds..."
    );


    delay(2000);
}
