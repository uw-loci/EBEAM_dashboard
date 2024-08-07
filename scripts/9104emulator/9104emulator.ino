String inputString = "";
bool stringComplete = false;

float voltage = 0.0;
float current = 0.0;
bool outputOn = false;
float maxVoltage = 50.0;
float maxCurrent = 10.0;
int preset = 3;

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
    if (inChar != '\n') {  // Ignore spaces and newlines
      inputString += inChar;
      if (inChar == '\r') {
        stringComplete = true;
      }
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
    preset = 3;
    Serial.println("OK");
  }
  else if (command == "GABC") {
    Serial.println(String(preset));
    Serial.println("OK");
  }
  else if (command.startsWith("VOLT")) {
    // Find the position of '3' in the command
    int valueStartIndex = command.indexOf('3');
    if (valueStartIndex != -1 && valueStartIndex < command.length() - 1) {
      // Extract the value part, ignoring any spaces
      String valueStr = command.substring(valueStartIndex + 1);
      valueStr.trim();  // Remove any leading/trailing spaces
      float newVoltage = valueStr.toFloat() / 100.0;
      if (newVoltage >= 0 && newVoltage <= maxVoltage) {
        voltage = newVoltage;
        Serial.println("OK");
      } else {
        Serial.println("ERROR: Voltage out of range");
      }
    } else {
      Serial.println("ERROR");
    }
  }
  else if (command.startsWith("CURR")) {
    int valueStartIndex = command.indexOf('3');
    if (valueStartIndex != -1 && valueStartIndex < command.length() - 1) {
      String valueStr = command.substring(valueStartIndex + 1);
      valueStr.trim();
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
  else if (command == "GETS3") {
    char response[12];
    sprintf(response, "%04d%04d", int(voltage * 100), int(current * 100));
    Serial.println(response);
    Serial.println("OK");
  }
  else if (command == "GETD") {
    float actualVoltage = outputOn ? voltage : 0.0;
    float actualCurrent = outputOn ? min(current, voltage / 100.0) : 0.0;
    int mode = 0; // CV mode
    char response[11];
    sprintf(response, "%04d%04d%d", int(actualVoltage * 100), int(actualCurrent * 100), mode);
    Serial.println(response);
    Serial.println("OK");
    delay(100);
  }
  else {
    Serial.println("Err");
    delay(100);
  }
}
