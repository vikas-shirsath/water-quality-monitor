# ESP32 firmware setup

Open `water_quality_monitor.ino` in Arduino IDE with an ESP32 board/core installed. Install the `OneWire` and `DallasTemperature` libraries; `WiFi`, `WiFiClientSecure`, and `HTTPClient` come with the ESP32 Arduino core. Copy `secrets.h.example` to `secrets.h` in this folder and edit the Wi-Fi values there. `secrets.h` is ignored by Git so the credentials won't be committed.

Before flashing:

1. Set `WIFI_SSID` and `WIFI_PASSWORD` in `secrets.h`. Use a 2.4 GHz Wi-Fi network; the original ESP32 does not connect to 5 GHz. For Wokwi, use `Wokwi-GUEST` and an empty password.
2. Calibrate `PH7_VOLTAGE` and `PH4_VOLTAGE` from the actual probe readings in pH 7 and pH 4 buffer solutions.
3. Match `TURBIDITY_USES_DIVIDER` to the wiring. Keep every analog voltage at the ESP32 ADC pin within its electrical limits and connect sensor/ESP32 grounds.
4. Leave `API_URL` pointed at the public FastAPI `/api/readings` endpoint. Do not use `localhost` and do not put Supabase credentials in firmware.

The sketch syncs the clock with NTP so HTTPS certificate dates can be checked, then sends one JSON POST every 30 seconds. The API assigns the UTC timestamp, stores each measurement in Supabase, evaluates thresholds, and emits WebSocket events for the dashboard. `ca_certificate.h` contains the current root from the verified Render certificate chain; update it if Render changes certificate authorities.
