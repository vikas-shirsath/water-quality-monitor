#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <math.h>
#include <time.h>
#include "secrets.h"
#include "ca_certificate.h"

// -------- Wi-Fi and backend --------
const char *DEVICE_ID = "WQM-001";
const char *API_URL = "https://water-quality-monitor-dyac.onrender.com/api/readings";

// The API/device heartbeat is configured for 30 seconds.
const unsigned long SAMPLE_INTERVAL_MS = 30000UL;

// -------- Sensor pins --------
#define TEMP_PIN 4
#define TDS_PIN 35
#define PH_PIN 32
#define TURBIDITY_PIN 34

// Calibrate these from the pH 7 and pH 4 buffer readings on GPIO32.
// Values below are placeholders; replace them with measured voltages.
float PH7_VOLTAGE = 1.65f;
float PH4_VOLTAGE = 2.00f;

// true when the turbidity output uses the 10k + 20k voltage divider.
#define TURBIDITY_USES_DIVIDER true

OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);
WiFiClientSecure tlsClient;
bool clockIsSet = false;

int readAverage(int pin, int samples = 20) {
  long sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  return static_cast<int>(sum / samples);
}

bool connectWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("Connecting to Wi-Fi: %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    const unsigned long started = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - started < 20000UL) {
      delay(250);
      Serial.print('.');
    }
    Serial.println();

    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("Wi-Fi connection failed; will retry next sample.");
      return false;
    }

    Serial.print("Wi-Fi connected. IP: ");
    Serial.println(WiFi.localIP());
  }

  // Certificate-date validation needs a real clock. Set it over NTP before
  // the first TLS request; Render's certificate is checked by the CA below.
  if (!clockIsSet) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    const unsigned long started = millis();
    time_t now = time(nullptr);
    while (now < 1700000000 && millis() - started < 15000UL) {
      delay(250);
      now = time(nullptr);
    }
    clockIsSet = now >= 1700000000;
    if (!clockIsSet) {
      Serial.println("NTP time sync failed; TLS request deferred.");
      return false;
    }
    Serial.println("Clock synchronized for HTTPS certificate validation.");
  }
  return true;
}

bool postReading(float ph, float tdsPpm, float turbidityNtu, float tempC) {
  if (!connectWiFi()) return false;

  char payload[256];
  const int length = snprintf(
      payload, sizeof(payload),
      "{\"device_id\":\"%s\",\"ph\":%.2f,\"tds\":%.1f,\"turbidity\":%.1f,\"temperature\":%.2f}",
      DEVICE_ID, ph, tdsPpm, turbidityNtu, tempC);
  if (length <= 0 || length >= static_cast<int>(sizeof(payload))) {
    Serial.println("Could not format the sensor payload.");
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(60000);
  http.setTimeout(60000);
  if (!http.begin(tlsClient, API_URL)) {
    Serial.println("Could not initialize HTTPS request.");
    return false;
  }

  http.addHeader("Content-Type", "application/json");
  Serial.print("POST ");
  Serial.println(API_URL);
  Serial.print("Payload: ");
  Serial.println(payload);

  const int statusCode = http.POST(reinterpret_cast<uint8_t *>(payload), length);
  const String response = statusCode > 0 ? http.getString() : http.errorToString(statusCode);
  Serial.printf("Backend response: HTTP %d — %s\n", statusCode, response.c_str());
  http.end();
  return statusCode == 201;
}

void setup() {
  Serial.begin(115200);
  delay(200);
  tempSensor.begin();

  analogReadResolution(12);
  analogSetPinAttenuation(TDS_PIN, ADC_11db);
  analogSetPinAttenuation(PH_PIN, ADC_11db);
  analogSetPinAttenuation(TURBIDITY_PIN, ADC_11db);

  // Validate the Render HTTPS certificate against the bundled root CA.
  tlsClient.setCACert(RENDER_ROOT_CA);

  connectWiFi();
  Serial.println("Water quality monitor ready.");
}

void loop() {
  // -------- Temperature (DS18B20) --------
  tempSensor.requestTemperatures();
  const float tempC = tempSensor.getTempCByIndex(0);
  if (tempC == DEVICE_DISCONNECTED_C || !isfinite(tempC) || tempC < -55.0f || tempC > 125.0f) {
    Serial.println("Temperature sensor missing/invalid; skipping upload (temperature is required by the API).");
    delay(SAMPLE_INTERVAL_MS);
    return;
  }
  Serial.printf("Temperature: %.2f C\n", tempC);

  // -------- TDS --------
  const int tdsRaw = readAverage(TDS_PIN);
  const float tdsVoltage = tdsRaw * 3.3f / 4095.0f;
  const float compensation = 1.0f + 0.02f * (tempC - 25.0f);
  const float compensatedVoltage = tdsVoltage / compensation;
  float tdsPpm = (133.42f * compensatedVoltage * compensatedVoltage * compensatedVoltage
                  - 255.86f * compensatedVoltage * compensatedVoltage
                  + 857.39f * compensatedVoltage) * 0.5f;
  if (!isfinite(tdsPpm)) {
    Serial.println("Invalid TDS measurement; skipping upload.");
    delay(SAMPLE_INTERVAL_MS);
    return;
  }
  if (tdsPpm < 0.0f) tdsPpm = 0.0f;
  Serial.printf("TDS raw=%d voltage=%.3f V value=%.1f ppm\n", tdsRaw, tdsVoltage, tdsPpm);

  // -------- pH --------
  const int phRaw = readAverage(PH_PIN);
  const float phVoltage = phRaw * 3.3f / 4095.0f;
  const float calibrationSpan = PH4_VOLTAGE - PH7_VOLTAGE;
  if (fabsf(calibrationSpan) < 0.001f) {
    Serial.println("pH calibration voltages are invalid; check PH7_VOLTAGE/PH4_VOLTAGE.");
    delay(SAMPLE_INTERVAL_MS);
    return;
  }
  const float phValue = 7.0f + (phVoltage - PH7_VOLTAGE) * (4.0f - 7.0f) / calibrationSpan;
  Serial.printf("pH raw=%d voltage=%.3f V value=%.2f\n", phRaw, phVoltage, phValue);

  // API validation accepts pH only within 0..14. Do not upload an uncalibrated
  // or disconnected sensor value as if it were a valid measurement.
  if (!isfinite(phValue) || phValue < 0.0f || phValue > 14.0f || phVoltage < 0.05f || phVoltage > 3.2f) {
    Serial.println("pH measurement outside API/calibration range; skipping upload.");
    delay(SAMPLE_INTERVAL_MS);
    return;
  }

  // -------- Turbidity --------
  const int turbRaw = readAverage(TURBIDITY_PIN);
  const float turbidityPinVoltage = turbRaw * 3.3f / 4095.0f;
  const float turbiditySensorVoltage = TURBIDITY_USES_DIVIDER
      ? turbidityPinVoltage * 1.5f
      : turbidityPinVoltage;

  float ntu;
  if (turbiditySensorVoltage < 2.5f) {
    ntu = 3000.0f;
  } else {
    ntu = -1120.4f * turbiditySensorVoltage * turbiditySensorVoltage
          + 5742.3f * turbiditySensorVoltage - 4352.9f;
    if (ntu < 0.0f) ntu = 0.0f;
  }
  Serial.printf("Turbidity raw=%d pin=%.3f V sensor=%.3f V value=%.1f NTU\n",
                turbRaw, turbidityPinVoltage, turbiditySensorVoltage, ntu);

  // The backend validates turbidity in the 0..10000 range.
  if (!isfinite(ntu) || ntu < 0.0f || ntu > 10000.0f) {
    Serial.println("Turbidity measurement outside API range; skipping upload.");
  } else {
    postReading(phValue, tdsPpm, ntu, tempC);
  }

  Serial.println("----------------------------");
  delay(SAMPLE_INTERVAL_MS);
}
