#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include "defs.h"
 
const int VIBRATION_SENSOR = 5;
unsigned long last_measurement = 0;

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
    mqttClient.subscribe("sherangthebell/status");

    Serial.println("Connected to the MQTT Server!");
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Topic: ");
  Serial.println(topic);
 
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

  unsigned long now = millis();
  long measurement = pulseIn(VIBRATION_SENSOR, HIGH);
  
  if (measurement > 1000) {   
    char str_measurement[5];
    dtostrf(measurement, 5, 0, str_measurement);

    if (now >= (last_measurement + bellDelay)) {
      Serial.print("Measurament: ");
      Serial.println(str_measurement);
      mqttClient.publish("sherangthebell/bell", str_measurement);
      last_measurement = now;
    }
  }
}
