#include "SPIFFS.h"


void setup() {

  Serial.begin(115200);

// ------------------- DEBUGGING TO SEE THE FILES CONTAINED IN THE ESP ------------ //
 
  if (!SPIFFS.begin(true))  {
    Serial.println("An error has occurred while mounting SPIFFS");
    return;
  }

//  File root = SPIFFS.open("/");
//  File file = root.openNextFile();
//
//  while(file) {
//    Serial.print("File: ");
//    Serial.println(file.name());
//    file = root.openNextFile();
//  }



// ---------------------------- READING THE FILE ------------------------------ //

  File file = SPIFFS.open("/C_phi_L3.csv", "r");
  
  if (!file) {
    Serial.println("Failed to open file");
    return;
  }

  while (file.available()) {
    String line = file.readStringUntil('\n');
    Serial.println(line);
  }

  file.close();
}

void loop() {

  
}
