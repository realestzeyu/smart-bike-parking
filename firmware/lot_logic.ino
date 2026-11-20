
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// IOT setup

const char* WIFI_SSID = "XXXX";
const char* WIFI_PASSWORD = "XXXX";

const char* AWS_ENDPOINT = "XXXX";

const char* THING_NAME = "space1_lot1";

const char* MQTT_TOPIC = "space1/lot1/event";

const char* CONTROL_TOPIC = "space1/lot1/cmd";

WiFiClientSecure secureClient;
PubSubClient mqttClient(secureClient);

const char AWS_ROOT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
XXX
-----END CERTIFICATE-----
)EOF";

const char DEVICE_CERT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
XXX
-----END CERTIFICATE-----
)EOF";

const char PRIVATE_KEY[] PROGMEM = R"EOF(
-----BEGIN RSA PRIVATE KEY-----
XXX
-----END RSA PRIVATE KEY-----
)EOF";

const int vibrationSensorPin = 19;
const int irSensorPin = 18;
const int solenoidLockPin = 21;
const int solenoidFeedbackPin = 4;

bool vibrationDetected = false;
bool irDetected = false;

bool previousIRState = HIGH;
bool previousLockState = HIGH;

unsigned long lastVibrationCheck = 0;
const unsigned long vibrationCheckInterval = 2000;
bool vibrationDetectedInWindow = false;

bool unlockRequested = false;
bool solenoidActive = false;

unsigned long unlockStartTime = 0;
const unsigned long unlockDuration = 500; // 0.5 seconds

// WIFI connection
void connectWiFi() {

  Serial.println("Starting WiFi connection...");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
  }

  Serial.println("\nWiFi connected!");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {

    Serial.println("Starting MQTT connection");

    while (!mqttClient.connected()) {

        Serial.println("Connecting to AWS IoT Core...");

        if (mqttClient.connect(THING_NAME)) {

            Serial.println("MQTT Connected!");

            // Subscribe to lock control topic
            if (mqttClient.subscribe(CONTROL_TOPIC)) {
                Serial.println("Subscribed to lock control topic!");
            } else {
                Serial.println("Failed to subscribe!");
            }

        } else {

            Serial.print("Failed, state: ");
            Serial.println(mqttClient.state());

            delay(2000);
        }
    }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {

    if (strcmp(topic, CONTROL_TOPIC) == 0) {

      JsonDocument doc;

      DeserializationError error = deserializeJson(doc, payload, length);

      if (error) {
          Serial.println("Invalid JSON!");
          return;
      }

      const char* action = doc["action"];

      if (action != nullptr && strcmp(action, "open") == 0) {

          if (!solenoidActive && !unlockRequested) {
              Serial.println("Unlock command received!");
              unlockRequested = true;
          } else {
              Serial.println("Unlock ignored - solenoid busy!");
          }
      }
  }
}

void setup() {
  Serial.begin(9600);         // Start serial communication at 9600 baud rate
  pinMode(vibrationSensorPin, INPUT);  // Set the sensorPin as an input pin
  pinMode(irSensorPin, INPUT);  // Set the sensorPin as an input pin
  pinMode(solenoidLockPin, OUTPUT);
  pinMode(solenoidFeedbackPin, INPUT_PULLUP);

  // Fail-secure: keep lock locked by default
  digitalWrite(solenoidLockPin, HIGH);
  previousLockState = digitalRead(solenoidFeedbackPin);

  // wifi & mqtt setup
  connectWiFi();

  secureClient.setCACert(AWS_ROOT_CA);
  secureClient.setCertificate(DEVICE_CERT);
  secureClient.setPrivateKey(PRIVATE_KEY);

  mqttClient.setServer(AWS_ENDPOINT, 8883);
  mqttClient.setCallback(mqttCallback);

  connectMQTT();
}

void loop() {

  // Maintain MQTT connection
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("WiFi disconnected!");

    // Force solenoid HIGH for safety
    digitalWrite(solenoidLockPin, HIGH);
    solenoidActive = false;
    unlockRequested = false;

    connectWiFi();
  }

  // Check MQTT connection
  if (!mqttClient.connected()) {

    Serial.println("MQTT disconnected!");

    // Force solenoid HIGH for safety
    digitalWrite(solenoidLockPin, HIGH);
    solenoidActive = false;
    unlockRequested = false;

    connectMQTT();
  }
  mqttClient.loop();  

  // ================= REMOTE UNLOCK =================

    // Process unlock request
  if (unlockRequested && !solenoidActive) {

      Serial.println("Solenoid activated - unlocking!");
      digitalWrite(solenoidLockPin, LOW);

      solenoidActive = true;
      unlockStartTime = millis();

      unlockRequested = false;

  }

  // Automatically deactivate solenoid after 0.5 seconds
  if (solenoidActive &&
    millis() - unlockStartTime >= unlockDuration) {

    digitalWrite(solenoidLockPin, HIGH);

    solenoidActive = false;

    Serial.println("Solenoid deactivated - pulse completed!");
}

  // ================= VIBRATION DETECTION =================

  // Continuously monitor vibration sensor
  if (digitalRead(vibrationSensorPin) == HIGH) {
    vibrationDetectedInWindow = true;
  }

  // Every 2 seconds, send at most one notification
  if (millis() - lastVibrationCheck >= vibrationCheckInterval) {

    lastVibrationCheck = millis();

    if (vibrationDetectedInWindow) {

        Serial.println("Vibration detected during the last 2 seconds!");

        mqttClient.publish(MQTT_TOPIC,
            "{\"type\":\"tamper\"}");
    }

    // Reset for the next 2-second window
    vibrationDetectedInWindow = false;
  }

  // ================= IR DETECTION =================

  bool currentIRState = digitalRead(irSensorPin);

  if (currentIRState != previousIRState) {

      irDetected = (currentIRState == LOW);

      Serial.println(irDetected ? "IR detected!" : "IR no longer detected!");

      char payload[100];

      snprintf(payload, sizeof(payload),
          "{\"type\":\"%s\"}",
          irDetected ? "bike_arrived" : "bike_left");

      mqttClient.publish(MQTT_TOPIC, payload);

      previousIRState = currentIRState;
      
  }


  // ================= LOCK STATE CHANGE =================

  bool currentLockState = digitalRead(solenoidFeedbackPin);

  bool isLocked = !currentLockState;

  if (currentLockState != previousLockState) {

      Serial.println(isLocked ? "Lock closed!" : "Lock open!");

      char payload[100];

      snprintf(payload, sizeof(payload),
        "{\"type\":\"%s\"}",
        isLocked ? "lock_closed" : "lock_opened");

      mqttClient.publish(MQTT_TOPIC, payload);

      previousLockState = currentLockState;
  }



  delay(10);
}
