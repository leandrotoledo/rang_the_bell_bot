#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include "defs.h"

const int LED_PIN = 5;
bool LED_STATUS = false;
const unsigned int DELAY_TIME = 1; // Milliseconds
const unsigned int MIN_LEVEL  = 0;
const unsigned int MAX_LEVEL  = 1023;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

void setup() {
  Serial.begin(115200);

  Serial.printf("Connecting to %s", ssid);
  WiFi.setAutoReconnect(true);
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(ssid, password);
  }
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("Connected to the WiFi!");

  mqttClient.setServer(mqttServer, mqttPort);
  mqttClient.setCallback(callback);
}

void mqttReconnect() {
  Serial.println("Connecting to the MQTT Server...");

  if (mqttClient.connect(mqttClientName)) {
    mqttClient.publish("sherangthebell/status", "connected");
    mqttClient.subscribe("sherangthebell/bell");
    mqttClient.subscribe("sherangthebell/take");

    Serial.println("Connected to the MQTT Server!");
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Topic: ");
  Serial.println(topic);

  if (strcmp(topic, "sherangthebell/bell") == 0) {
    Serial.println("Enabling LED");
    LED_STATUS = true;
  }

  if (strcmp(topic, "sherangthebell/take") == 0) {
    Serial.println("Disabling LED");
    LED_STATUS = false;
  }

  Serial.print("Message: ");
  for (int i = 0; i < length; i++) {
    Serial.print((char)payload[i]);
  }
  Serial.println();
}

void loop() {
  if (!mqttClient.connected()) {
    mqttReconnect();
  }
  mqttClient.loop();

  if (LED_STATUS == true) {
    unsigned int i;
    for (i = MIN_LEVEL; i < MAX_LEVEL; i++)
      analogWriteDelay(LED_PIN, i, DELAY_TIME);
    for (i = MAX_LEVEL; i > MIN_LEVEL; i--)
      analogWriteDelay(LED_PIN, i, DELAY_TIME);
  }

  if (LED_STATUS == false) {
    digitalWrite(LED_BUILTIN, LOW);
  }
}

void analogWriteDelay(unsigned int pin,
                      unsigned int value,
                      unsigned int waitTime) {
  analogWrite(pin, value); // Analog write in LED pin
  delay(waitTime);        // Delay in milliseconds
}
