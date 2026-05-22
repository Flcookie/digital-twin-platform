// --------------------------------------------------- LIBRARIES ---------------------------------------------------
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <MqttClient.h>
// -----------------------------------------------------------------------------------------------------------------

// ---------------------------------------------------- MARCOS -----------------------------------------------------
#define STATION_ID "Test"
#define SPI_SS_PIN  5
#define SPI_RST_PIN 22
#define WIFI_SSID     "THE FACTORY - ROUTER 1"
#define WIFI_PASSWORD "legofactory"
#define MQTT_BROKER_HOST  "THE-FACTORY-PC1"
#define MQTT_BROKER_PORT  1883
#define MQTT_CLIENT_ID    STATION_ID "-ESP32"
#define MQTT_BUFFER_SIZE  128
#define MQTT_TOPIC_SIZE   64
#define MQTT_PAYLOAD_SIZE 64
#define STATUS_START 0
#define STATUS_STOP  1
// -----------------------------------------------------------------------------------------------------------------

// --------------------------------------------------- VARIABLES ---------------------------------------------------
MFRC522 mfrc522 = MFRC522();
WiFiClient wifiClient = WiFiClient();
MqttClient::Options mqttOptions;
MqttClient::Logger &&mqttLogger = MqttClient::LoggerImpl<HardwareSerial>(Serial);
class System : public MqttClient::System {
  public:
    unsigned long millis() const { return ::millis(); }
    void yield(void) { ::yield(); }
};
MqttClient::System &&mqttSystem = System();
MqttClient::Network &&mqttNetwork = MqttClient::NetworkClientImpl<WiFiClient>(wifiClient, mqttSystem);
MqttClient::Buffer &&mqttSendBuffer = MqttClient::ArrayBuffer<MQTT_BUFFER_SIZE>();
MqttClient::Buffer &&mqttRecvBuffer = MqttClient::ArrayBuffer<MQTT_BUFFER_SIZE>();
MqttClient::MessageHandlers &&mqttMsgHandlers = MqttClient::MessageHandlersDynamicImpl<1>();
MqttClient mqttClient = MqttClient(mqttOptions, mqttLogger, mqttSystem, mqttNetwork, mqttSendBuffer, mqttRecvBuffer, mqttMsgHandlers);
MQTTPacket_connectData mqttConnOptions = MQTTPacket_connectData_initializer;
MqttClient::ConnectResult mqttConnResult;
char mqttTopic[MQTT_TOPIC_SIZE];
MqttClient::Message mqttMsg = {MqttClient::QOS2, false, false, 0, NULL, 0};
MqttClient::Error::type mqttErr = MqttClient::Error::SUCCESS;
int systemStatus = STATUS_STOP;
bool isFirstRun = true;
// -----------------------------------------------------------------------------------------------------------------

// ------------------------------------------------- SETUP FUNCTION ------------------------------------------------
void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.println("This code reads a PICC card and sends its UID via MQTT");

  // Initialize MFRC522
  SPI.begin();
  mfrc522.PCD_Init(SPI_SS_PIN, SPI_RST_PIN);

  // Initialize WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  delay(5000);

  // Initialize MQTT
  strcpy(mqttTopic, "system_status/master/all");
  mqttMsgHandlers.set(mqttTopic, mqttCallback);
  mqttConnOptions.clientID.cstring = (char *) MQTT_CLIENT_ID;
  wifiClient.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
  mqttClient.connect(mqttConnOptions, mqttConnResult);
  mqttClient.subscribe(mqttTopic, MqttClient::QOS2);
  delay(5000);
}
// -----------------------------------------------------------------------------------------------------------------

// ------------------------------------------------- LOOP FUNCTION -------------------------------------------------
void loop() {
  // Check the connection to WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Failed to connect to WiFi");
    delay(3000);
    return;
  }

  // Check the connection to MQTT
  if (!mqttClient.isConnected()) {
    Serial.println("Failed to connect to MQTT");
    delay(3000);
    wifiClient.stop();
    wifiClient.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    mqttClient.connect(mqttConnOptions, mqttConnResult);
    strcpy(mqttTopic, "system_status/master/all");
    mqttClient.subscribe(mqttTopic, MqttClient::QOS2);
    return;
  }
  mqttClient.yield(200);

  // Check if the system is stopped
  if (systemStatus == STATUS_STOP) {
    // Reset to the first run
    isFirstRun = true;
    return;
  }

  // Check if the last MQTT message failed
  if (mqttErr != MqttClient::Error::SUCCESS) {
    // Publish the last MQTT message again
    mqttErr = mqttClient.publish(mqttTopic, mqttMsg);
    return;
  }

  // Check if this is the first run
  if (isFirstRun) {
    // Check the presence of a card and the readiness of its UID
    if (!mfrc522_PICC_IsCardPresent() || !mfrc522.PICC_ReadCardSerial()) {
      return;
    }
    isFirstRun = false;
  } else {
    // Check the presence of a new card and the readiness of its UID
    if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) {
      return;
    }
  }
  // Get the card UID in the hexadecimal format
  const char* part_uid = mfrc522_GetHexUid();
  Serial.println(part_uid);

  // Publish the MQTT message
  mqttMsg.payload = (void *) part_uid;
  mqttMsg.payloadLen = strlen(part_uid);
  strcpy(mqttTopic, "part_uid/" STATION_ID "/all");
  mqttErr = mqttClient.publish(mqttTopic, mqttMsg);

  // Halt the PICC card
  mfrc522.PICC_HaltA();

  // Stop the encryption on MFRC522
  mfrc522.PCD_StopCrypto1();
}
// -----------------------------------------------------------------------------------------------------------------

// ---------------------------------------------- AUXILIARY FUNCTIONS ----------------------------------------------
void mqttCallback(MqttClient::MessageData& msgData) {
  const char* payload = (char *) msgData.message.payload;
  int payloadLen = msgData.message.payloadLen;
  char newStatus[8];
  for (byte i = 0; i < payloadLen; i++) {
    newStatus[i] = toupper(payload[i]);
  }
  newStatus[payloadLen] = '\0';

  if (strcmp(newStatus, "START") == 0) {
    if (systemStatus == STATUS_STOP) {
      delay(1000);
    }
    systemStatus = STATUS_START;
  } else if (strcmp(newStatus, "STOP") == 0) {
    systemStatus = STATUS_STOP;
  }
}

bool mfrc522_PICC_IsCardPresent() {
  byte buffer[2];
  byte size = 2;
  mfrc522.PCD_WriteRegister(MFRC522::TxModeReg, 0x00);
  mfrc522.PCD_WriteRegister(MFRC522::RxModeReg, 0x00);
  mfrc522.PCD_WriteRegister(MFRC522::ModWidthReg, 0x26);
  MFRC522::StatusCode code = mfrc522.PICC_WakeupA(buffer, &size);
  return (code == MFRC522::STATUS_OK || code == MFRC522::STATUS_COLLISION);
}

const char* mfrc522_GetHexUid() {
  static char uid[23];
  uid[0] = '0';
  uid[1] = 'x';
  for (byte i = 0; i < mfrc522.uid.size; i++) {
    byte high = (mfrc522.uid.uidByte[i] >> 4) & 0x0F;
    byte low  = (mfrc522.uid.uidByte[i] >> 0) & 0x0F;
    uid[i * 2 + 2] = (high < 0x0A) ? ('0' + high) : ('A' + high - 0x0A);
    uid[i * 2 + 3] = (low  < 0x0A) ? ('0' + low ) : ('A' + low  - 0x0A);
    uid[mfrc522.uid.size * 2 + 2] = '\0';
  }
  return uid;
}
// -----------------------------------------------------------------------------------------------------------------
