String inputString = "";
bool stringComplete = false;

float voltage = 0.0;
float current = 0.0;
bool outputOn = false;
float maxVoltage = 50.0;
float maxCurrent = 10.0;

void setup() {
  Serial.begin(9600);
  inputString.reserve(200);
}

void loop() {
  if (stringComplete) {
    processCommand(inputString);
    inputString = "";
    stringComplete = false;
  }
}

void serialEvent() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    inputString += inChar;
    if (inChar == '\r') {
      stringComplete = true;
    }
  }
}

void processCommand(String command) {
  command.trim();
  
  if (command.startsWith("SOUT")) {
    outputOn = (command.charAt(4) == '1');
    Serial.println("OK");
  }
  else if (command == "SABC3") {
    Serial.println("OK");
  }
  else if (command.startsWith("VOLT")) {
    int valueStartIndex = command.indexOf('3', 4) + 1;
    if (valueStartIndex > 4) { 
      String valueStr = command.substring(valueStartIndex);
      float newCurrent = valueStr.toFloat() / 100.0;
      if (newCurrent >= 0 && newCurrent <= maxCurrent) {
        current = newCurrent;
        Serial.println("OK");
      } else {
        Serial.println("ERROR: Current out of range");
      }
    } else {
      Serial.println("ERROR");
    }
  }
  else if (command.startsWith("CURR")) {
    int valueStartIndex = command.indexOf('3', 4) + 1; 
    if (valueStartIndex > 4) { 
      String valueStr = command.substring(valueStartIndex);
      current = valueStr.toFloat() / 100.0;
      Serial.println("OK");
    } else {
      Serial.println("ERROR");
    }
  }
  else if (command == "GETS 3") {
    char response[12];
    sprintf(response, "%04d %04d", int(voltage * 100), int(current * 100));
    Serial.println(response);
  }
  else if (command == "GETD") {
    float actualVoltage = outputOn ? voltage : 0.0;
    float actualCurrent = outputOn ? min(current, voltage / 100.0) : 0.0;
    int mode = 0; // CV mode
    char response[20];
    sprintf(response, "%04d %04d %d", int(actualVoltage * 100), int(actualCurrent * 100), mode);
    Serial.println(response);
  }
  else {
    Serial.println("ERROR");
  }
}