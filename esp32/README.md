# ESP32 firmware setup

The complete firmware is in one file: `water_quality_monitor.ino`. Open it in Arduino IDE. No `secrets.h` or certificate header is required; the sketch contains the HTTPS certificate and editable Wi-Fi placeholders.

Install the Espressif ESP32 board package and the `OneWire` and `DallasTemperature` libraries. The ESP32 Arduino board package supplies `WiFi`, `WiFiClientSecure`, and `HTTPClient`.

Before uploading, edit `WIFI_SSID`, `WIFI_PASSWORD`, `PH7_VOLTAGE`, and `PH4_VOLTAGE` in the sketch. Use a 2.4 GHz Wi-Fi network. Calibrate the pH voltages using pH 7 and pH 4 buffer solutions, measured at the ESP32 input after any divider. Match `TURBIDITY_USES_DIVIDER` to your wiring. Keep every ESP32 analog input between 0 and 3.3 V and connect sensor and board grounds.

The sketch syncs time with NTP, validates Render HTTPS using its bundled root CA, and posts readings every 30 seconds to `/api/readings`. Do not replace the public backend URL with `localhost` or put Supabase credentials in the firmware. The backend stores readings in Supabase and updates the dashboard.
