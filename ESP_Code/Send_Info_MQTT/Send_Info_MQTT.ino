#include "SPIFFS.h"
#include <ArduinoJson.h>
#include <WiFi.h>
#include <PubSubClient.h>
#define ARDUINOJSON_DEFAULT_NESTING_LIMIT 0

// ---------------------------- WI-FI VARIABLES -------------------------------- //

//// c2e
//const char* ssid = "default";
//const char* password = "";

// eduroam (hotspot from my phone)
const char* ssid = "José's Galaxy S21 5G";
const char* password = "lemc0316";

// ---------------------------- MQTT VARIABLES --------------------------------- //

// MQTT topic variables
String tenant = "ESPTenant";
String namespace_l = "av101";
String device_name = "ESP_32";
String mqtt_topic = "telemetry/" + tenant + "/" + namespace_l + ":" + device_name;

// c2e
//const char* mqtt_server = "192.168.1.5";
//int mqtt_port = 31883;
String mqtt_user = device_name + "_ID@" + tenant;
String mqtt_pass = device_name + "_pass";

// mosquitto broker - ua
const char* mqtt_server = "192.168.193.244";
int mqtt_port = 1883;

// ---------------------------- SOME OBJECTS ----------------------------------- //

WiFiClient espClient; // wifi object
PubSubClient client(espClient); // mqtt object

  
void setup() {

  Serial.begin(115200);

  // Seeing if we can read the values from the csv in the ESP
  if (!SPIFFS.begin(true))  {
    Serial.println("An error has occurred while mounting SPIFFS");
    return;
  }

  // ------------------------- WI-FI SETUP -------------------------------------- //
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED) {
      delay(1000);
      Serial.println("Connecting to WiFi...");
    }
    
    Serial.println("\n Connected to the WiFi network");
    Serial.print("Local ESP32 IP: ");
    Serial.println(WiFi.localIP());

  
  // ---------------------------- CONNECTING TO BROKER -------------------------- //
    client.setServer(mqtt_server, mqtt_port); // Replace with the IP address of your MQTT broker
    while(!client.connected()){
        // client.connect(device_name.c_str(), mqtt_user.c_str(), mqtt_pass.c_str()); // ESP registers in our broker
        client.connect(device_name.c_str());
        Serial.println("Attempting to connect to MQTT server...");
        delay(1000);
    }


}  // void setup



void loop() {

  // opening the file
  File file = SPIFFS.open("/C_phi_L3.csv", "r");
  if (!file) {
    Serial.println("Failed to open file " + file);
  }

  while (file.available()) {
    
    // ---------------------------- CONNECTING TO BROKER -------------------------- //
    if(!client.connected()){
        // client.connect(device_name.c_str(), mqtt_user.c_str(), mqtt_pass.c_str()); // ESP registers in our broker, with the name ESP32
        client.connect(device_name.c_str());
        Serial.println("Attempting to connect to MQTT server...");
        delay(1000);
    }
    client.loop();  

    String line;
    // getting the value from the line
    line = file.readStringUntil('\n');
    line.trim();
    // Extract the third column of the CSV (value)
    String value_var = line.substring(line.lastIndexOf(',') + 1);

    // creating the JSON file
    DynamicJsonDocument root(290);
    
    // Generating our json values
    root["topic"] = namespace_l + "/" + device_name + "/things/twin/commands/modify";
    root.createNestedObject("headers");
    root["path"] = "/features";
      
    JsonObject value  = root.createNestedObject("value");
        
    value["C_phi_L3"]["properties"]["value"] = value_var;
  
    
    // ------------------------------ PUBLISHING JSON ------------------------------ //
    
    String jsonPayload;
    serializeJson(root, jsonPayload);
  
    if (client.publish(mqtt_topic.c_str(), jsonPayload.c_str())) {
      Serial.println("\n Published JSON payload");
    } else {
      Serial.println("\n Failed to publish JSON payload");
    }
  
    Serial.println(mqtt_topic);
    
    // print out the formated json
    serializeJsonPretty(root, Serial);
  
    Serial.println("\n\n");
  
    delay(5000);
    
    }




  

}
