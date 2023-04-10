#include <ArduinoJson.h>
#include <WiFi.h>
#include <PubSubClient.h>
#define ARDUINOJSON_DEFAULT_NESTING_LIMIT 0

// ---------------------------- WI-FI VARIABLES -------------------------------- //

const char* ssid = "default";
const char* password = "";


// ---------------------------- MQTT VARIABLES --------------------------------- //

// MQTT topic variables
String tenant = "ESPTenant";
String namespace_l = "av101";
String device_name = "ESP_32";
String mqtt_topic = "telemetry/" + tenant + "/" + namespace_l + ":" + device_name;

// c2e
const char* mqtt_server = "192.168.1.5";
int mqtt_port = 31883;
String mqtt_user = device_name + "_ID@" + tenant;
String mqtt_pass = device_name + "_pass";


// ---------------------------- SOME OBJECTS ----------------------------------- //

WiFiClient espClient; // wifi object
PubSubClient client(espClient); // mqtt object

// JSON




void setup() {
  
  // Initialize Serial port
  Serial.begin(115200);
  while (!Serial) continue;

 
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
      client.connect(device_name.c_str(), mqtt_user.c_str(), mqtt_pass.c_str()); // ESP registers in our broker, with the name ESP32
      Serial.println("Attempting to connect to MQTT server...");
      delay(1000);
  }

} // void setup


void loop() {

  // ---------------------------- CONNECTING TO BROKER -------------------------- //
  
  while(!client.connected()){
      client.connect(device_name.c_str(), mqtt_user.c_str(), mqtt_pass.c_str()); // ESP registers in our broker, with the name ESP32
      Serial.println("Attempting to connect to MQTT server...");
      delay(1000);
  }
  client.loop();  

  // ----------------------------- GETTING THE VALUES TO SEND ---------------------------- //

  // Read free heap memory
  int freeHeap = ESP.getFreeHeap();
  
  // Read uptime
  unsigned long uptime = millis();
  
  // Read WiFi signal strength
  int wifiSignal = WiFi.RSSI();

  // ---------------------------- JSON GENERATION ------------------------------- //

  DynamicJsonDocument root(ESP.getMaxAllocHeap());
  Serial.println(ESP.getMaxAllocHeap());
//  DynamicJsonDocument root(290);
  
  // Generating our json values
  root["topic"] = namespace_l + "/" + device_name + "/things/twin/commands/modify";
  root.createNestedObject("headers");
  root["path"] = "/features";
    
  JsonObject value  = root.createNestedObject("value");
      
//  value["FreeHeap"]["properties"]["value"] = freeHeap;
  value["UpTime"]["properties"]["value"] = uptime;
  value["WifiSignal"]["properties"]["value"] = wifiSignal;

  
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
