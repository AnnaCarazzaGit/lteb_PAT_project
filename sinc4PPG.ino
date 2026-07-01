#include <bluefruit.h>
#include <Wire.h>
#include <SparkFun_Bio_Sensor_Hub_Library.h>
#include <SparkFun_RV8803.h> 
#define ENABLE_max 0x01     // 0x01 abilita il sensore

// -------------------------------------------------------------------------
// CONFIGURAZIONE TEMPORALE (256 Hz) perchè meglio per PPG
// -------------------------------------------------------------------------
const int INITIAL_PACKET_SAMPLES = 128; // 0.5 secondi a 256Hz
const int FULL_SECOND_SAMPLES = 256;    // 1.0 secondo a 256Hz

// --- PIN ---
const int PIN_RTC_INT = 28; // Pin fisico collegato all'INT dell'RTC
const int resPin = 3; //9;       
const int mfioPin = 2; //10;     

// --- OGGETTI ---
BLEUart bleuart;
SparkFun_Bio_Sensor_Hub bioHub(resPin, mfioPin);
RV8803 rtc; 

// --- BUFFER --- due buffer così mentre invio uno, scrivo sull'altro e viceversa
uint16_t bufferA[FULL_SECOND_SAMPLES];
uint16_t bufferB[FULL_SECOND_SAMPLES];

// --- VARIABILI GESTIONE ---
volatile uint32_t global_tick_counter = 0; 
volatile bool sample_request = false;     // Volatile perché modificata da ISR

// Gestione Buffer
bool fillingBufferA = true;                
int writeIndex = 0;                        
int currentTargetSamples = INITIAL_PACKET_SAMPLES;
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

// Variabili Helper aggiunte per compatibilità
bioData body; 

// -------------------------------------------------------------------------
// INTERRUPT SERVICE ROUTINE (ISR) - HARDWARE
// -------------------------------------------------------------------------
// Questa funzione viene chiamata dal Pin 13 ogni volta che l'RTC scatta
/* ISR snello per essere stabile e preciso. 
Leggo il sensore nel loop perchè la comunicazione I2C usa l'interrupt, quindi usare un
interrupt dentro un altro interrupt potrebbe causare blocchi.*/
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
  
  // Delay iniziale per stabilizzare
  delay(8000); 

  Wire.begin();
  Wire.setClock(400000);        // questo rende I2C il più veloce possibile

  delay(100); // lascia stabilizzare I2C

  // 1. SETUP SENSORE PPG
  int res = bioHub.begin();
  if (res == 0) Serial.println("Sensor Hub avviato (Sensor started!).");
  else {
      Serial.println("ERRORE: Sensor Hub non trovato (Could not communicate with the sensor!).");
      while(1);
  }
  
  Serial.println("Configuring Sensor....");

  // --- CONFIGURAZIONE MANUALE (Merge da PPG_acquisition) ---
  
  // enable del sensore
  uint8_t Err_enable = bioHub.max30101Control(ENABLE_max);
  if(Err_enable != SFE_BIO_SUCCESS)
    Serial.println("Error in sensor's enable");
  else
    Serial.println("sensor enabled");

  // 1️⃣ Seleziona output “raw sensor data” (Red + IR)
  // Anche se usiamo solo IR, la modalità RAW è la 0x01
  uint8_t Err_mode = bioHub.setOutputMode(0x01);
  if(Err_mode != SFE_BIO_SUCCESS)
    Serial.println("Error in output_mode definition");
  else
    Serial.println("Output mode defined");

  // 2️⃣ Disattiva AGC
  // Disattiva algoritmo automatico del gain
  uint8_t Err_agc = bioHub.agcAlgoControl(0);
  if(Err_agc != SFE_BIO_SUCCESS)
    Serial.println("Error in AGC enablement");
  else
    Serial.println("AGC disabled");

  // 3️⃣ Imposta parametri sensore
  // Sample Rate impostato a 1000Hz come richiesto
  uint8_t Err_sample_rate = bioHub.setSampleRate(1000); 
  
  // Impostiamo PulseWidth a 118 (invece di 411) per avere dati a 16 bit nativi.
  // 411 = 18 bit resolution (troppo per uint16_t), 118 = 16 bit resolution.
  uint8_t Err_pulse_width = bioHub.setPulseWidth(118);            
  
  // ADC Range impostato a 8192nA (sensibilità media)
  uint8_t Err_adc_range = bioHub.setAdcRange(8192);

  // Controlli di errore (presi da PPG_acquisition)
  if(Err_sample_rate != SFE_BIO_SUCCESS) Serial.println("Error in sample rate setting");
  else Serial.println("Sample rate setted to 1000Hz");

  if(Err_pulse_width != SFE_BIO_SUCCESS) Serial.println("Error in pulse width setting");
  else Serial.println("Pulse width setted to 118us (16-bit)");

  if(Err_adc_range != SFE_BIO_SUCCESS) Serial.println("Error in ADC range setting");
  else Serial.println("ADC range setted to 8192nA");

  // ---------------------------------------------------------


  // 2. SETUP RTC
  if (rtc.begin() == false) {
    Serial.println("ERRORE: RTC non trovato!");
    while(1);
  }
  
  // Garantire che il sistema parta da una situazione nota e stabile 
  rtc.disableAllInterrupts();
  rtc.clearAllInterruptFlags();
  
  // Configurazione per 256 Hz
  // Formula: 4096 Hz / Ticks = Freq -> 4096 / 16 = 256 Hz
  rtc.setCountdownTimerFrequency(COUNTDOWN_TIMER_FREQUENCY_4096_HZ);
  rtc.setCountdownTimerClockTicks(16); 
  
  rtc.enableHardwareInterrupt(TIMER_INTERRUPT);
  rtc.setCountdownTimerEnable(true); 

  // 3. SETUP PIN INTERRUPT
  pinMode(PIN_RTC_INT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_RTC_INT), rtc_isr_sampling, FALLING);
  
  // 4. SETUP BLE
  // Il primo comando aumenta MTU da 20 byte a 247 byte
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX); 
  Bluefruit.begin();
  Bluefruit.setTxPower(4); 
  Bluefruit.setName("boardPPG"); 
  Bluefruit.Periph.setDisconnectCallback(disconnect_callback); // per la funzione di disconnessione
  Bluefruit.Periph.setConnInterval(6, 12); 
  
  bleuart.begin();
  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(bleuart);
  Bluefruit.ScanResponse.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.start(0);
  Serial.println("SISTEMA PRONTO (RTC Mode). In attesa comando 'S'...");
}

// -------------------------------------------------------------------------
// LOOP PRINCIPALE
// -------------------------------------------------------------------------
void loop() {
  
  // --- FASE 0: ATTESA START --- quando il pc invia "s", entrambe le schede eseguono queste righe
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
        currentTargetSamples = INITIAL_PACKET_SAMPLES;
        
        running = true;
        rtc.enableHardwareInterrupt(TIMER_INTERRUPT); // Si parte!
      }
    }
    return; // Se non corre, non fare altro
  }

  // --- FASE 1: CAMPIONAMENTO (Priorità Alta) ---
  // Rispondiamo alla richiesta dell'ISR Hardware (RTC a 256Hz)
  if (sample_request) {
    sample_request = false;
    
    // Lettura I2C (BioHub) - Preleviamo il dato processato
    body = bioHub.readSensor();
    
    // Prendiamo SOLO irLed 
    uint16_t val = body.irLed;

    if (writeIndex == 0) {
      currentFillTimestamp = global_tick_counter;  // salviamo timestamp del primo campione
    }

    if (fillingBufferA) bufferA[writeIndex] = val;  // salva nel buffer corrente
    else                bufferB[writeIndex] = val;
    writeIndex++;

    // Se un buffer è pieno passa all'altro e fa partire l'invio BLE
    if (writeIndex >= currentTargetSamples) {
      if (fillingBufferA) {                        
        sendPtr = bufferA; 
        fillingBufferA = false;
      } 
      else { 
        sendPtr = bufferB;
        fillingBufferA = true; 
      }
      
      // Prepara tutte le variabili per il bluetooth
      sendSize = currentTargetSamples;
      sendTimestamp = currentFillTimestamp; 
      bufferReadyToSend = true;
      sendOffsetBytes = 0;
      writeIndex = 0;
      // Dopo il primo pacchetto corto, si normalizza a 1 secondo (256 campioni)
      if (currentTargetSamples == INITIAL_PACKET_SAMPLES) {
          currentTargetSamples = FULL_SECOND_SAMPLES;
      }
    }
  }

  // --- FASE 2: INVIO BLE ---
  if (bufferReadyToSend && !sample_request) {  // invia solo se c'è pacchetto pronto e non stiamo leggendo il sensore
    if (sendOffsetBytes == 0) {                // il primo dato è il timestamp
       bleuart.write((uint8_t*)&sendTimestamp, sizeof(uint32_t));
    }

    // frammentazione in pacchetti più piccoli da 40 byte
    int bytesTotalData = sendSize * sizeof(uint16_t);
    int chunkSize = 240;
    // 40 va bene per 256Hz (basso traffico)
    
    // controllo di fine invio
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