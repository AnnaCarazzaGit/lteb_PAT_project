#include <bluefruit.h>
#include <Wire.h>
#include <SparkFun_RV8803.h>

// -------------------------------------------------------------------------
// CONFIGURAZIONE TEMPORALE (512 Hz)
// -------------------------------------------------------------------------
const int FULL_SECOND_SAMPLES = 512;    // 1.0 secondo a 512Hz

// --- PIN ECG (AD8232) ---
const int PIN_RTC_INT = 2;
const int LED_PIN = 20;          // LED indicatore Lead Off
const int PIN_ECG = A7;
const int PIN_LO_PIU = 29;      // Leads-off detect +
const int PIN_LO_MENO = 5;      // Leads-off detect -

// --- OGGETTI ---
BLEUart bleuart;
RV8803 rtc; 

// --- BUFFER --- (Double Buffering)
uint16_t bufferA[FULL_SECOND_SAMPLES];
uint16_t bufferB[FULL_SECOND_SAMPLES];

// --- VARIABILI GESTIONE ---
volatile uint32_t global_tick_counter = 0; 
volatile bool sample_request = false;

// Gestione Buffer
bool fillingBufferA = true;                
int writeIndex = 0;                        
int currentTargetSamples = FULL_SECOND_SAMPLES; // Target fisso a 512

// Gestione Invio BLE
bool bufferReadyToSend = false;            
uint16_t* sendPtr = nullptr;               
int sendSize = 0;                          
int sendOffsetBytes = 0;

// Timestamp
uint32_t currentFillTimestamp = 0;         
uint32_t sendTimestamp = 0;                

// Stato Globale
bool running = false;

// -------------------------------------------------------------------------
// INTERRUPT SERVICE ROUTINE (ISR)
// -------------------------------------------------------------------------
void rtc_isr_sampling() {
  if (!running) return;
  global_tick_counter++;
  
  // Alza la bandierina per dire al loop: "Leggi il sensore ORA!"
  sample_request = true;
}

// ----------------------------------------------------------------
// DISCONNESSIONE BLE
// ------------------------------------------------------------------
// Funzione chiamata automaticamente quando il BLE cade
void disconnect_callback(uint16_t conn_handle, uint8_t reason) {
  (void) conn_handle;
  (void) reason;

  Serial.println("DISCONNESSO! Fermo l'acquisizione.");
  
  // Questa è la riga magica:
  running = false; 
  
  // Spegniamo anche l'interrupt per sicurezza finché non riparte
  rtc.disableAllInterrupts();
}

// -------------------------------------------------------------------------
// SETUP
// -------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  
  // Setup Hardware ECG
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW); // LED spento di default
  
  pinMode(PIN_LO_PIU, INPUT);
  pinMode(PIN_LO_MENO, INPUT);
  
  // Risoluzione ADC
  analogReadResolution(12); // 12-bit (0-4095) per nRF52

  Wire.begin();
  Wire.setClock(400000);

  // Setup RTC
  if (rtc.begin() == false) {
    Serial.println("ERRORE: RTC non trovato!");
    while(1);
  }
  
  rtc.disableAllInterrupts();
  rtc.clearAllInterruptFlags();
  
  // Configurazione per 512 Hz
  // Formula: 4096 Hz / Ticks = Freq -> 4096 / 8 = 512 Hz
  rtc.setCountdownTimerFrequency(COUNTDOWN_TIMER_FREQUENCY_4096_HZ);
  rtc.setCountdownTimerClockTicks(8); 
  
  rtc.enableHardwareInterrupt(TIMER_INTERRUPT);
  rtc.setCountdownTimerEnable(true); 

  // Setup PIN Interrupt
  pinMode(PIN_RTC_INT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_RTC_INT), rtc_isr_sampling, FALLING);
  
  // Setup BLE
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX); 
  Bluefruit.begin();
  Bluefruit.setTxPower(4); 
  Bluefruit.setName("boardECG"); 
  Bluefruit.Periph.setDisconnectCallback(disconnect_callback); // per la funzione di disconnessione
  Bluefruit.Periph.setConnInterval(6, 12); 
  
  bleuart.begin();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.start(0);
  
  Serial.println("SISTEMA PRONTO (ECG Mode 512Hz). In attesa comando 'S'...");
}

// -------------------------------------------------------------------------
// LOOP PRINCIPALE
// -------------------------------------------------------------------------
void loop() {
  
  // --- FASE 0: ATTESA START ---
  if (!running) {
    if (bleuart.available()) {
      char c = (char)bleuart.read();
      if (c == 'S' || c == 's') {
        Serial.println("START ricevuto.");
        // Reset Atomico RTC
        rtc.disableAllInterrupts();
        global_tick_counter = 0;
        
        writeIndex = 0;
        fillingBufferA = true;
        bufferReadyToSend = false;
        sendOffsetBytes = 0;
        // Reset target samples al valore fisso
        currentTargetSamples = FULL_SECOND_SAMPLES;
        
        running = true;
        rtc.enableHardwareInterrupt(TIMER_INTERRUPT); 
      }
    }
    return; 
  }

  // --- FASE 1: CAMPIONAMENTO (Priorità Alta) ---
  if (sample_request) {
    sample_request = false;
    
    // --- CONTROLLO LEAD OFF ---
    // Se LO+ o LO- sono alti, significa che gli elettrodi sono staccati.
    if ((digitalRead(PIN_LO_PIU) == 1) || (digitalRead(PIN_LO_MENO) == 1)) {
        digitalWrite(LED_PIN, HIGH); // Accendi LED
    } else {
        digitalWrite(LED_PIN, LOW);  // Spegni LED
    }

    // Lettura Analogica ECG
    uint16_t val = analogRead(PIN_ECG);
    
    if (writeIndex == 0) {
      currentFillTimestamp = global_tick_counter;
    }

    if (fillingBufferA) bufferA[writeIndex] = val;
    else                bufferB[writeIndex] = val;
    writeIndex++;

    if (writeIndex >= currentTargetSamples) {
      if (fillingBufferA) { 
        sendPtr = bufferA; 
        fillingBufferA = false;
      } 
      else { 
        sendPtr = bufferB;
        fillingBufferA = true; 
      }
      
      sendSize = currentTargetSamples;
      sendTimestamp = currentFillTimestamp; 
      bufferReadyToSend = true;
      sendOffsetBytes = 0;
      writeIndex = 0;
      
    }
  }

  // --- FASE 2: INVIO BLE ---
  if (bufferReadyToSend && !sample_request) {
    if (sendOffsetBytes == 0) {
       bleuart.write((uint8_t*)&sendTimestamp, sizeof(uint32_t));
    }

    int bytesTotalData = sendSize * sizeof(uint16_t);
    int chunkSize = 240; 
    
    if (sendOffsetBytes >= bytesTotalData) {
       bufferReadyToSend = false;
    } 
    else {
       int remaining = bytesTotalData - sendOffsetBytes;
       int len = (remaining > chunkSize) ? chunkSize : remaining;
       bleuart.write((uint8_t*)sendPtr + sendOffsetBytes, len);
       sendOffsetBytes += len;
    }
  }
}