# lteb_PATproject

Sistema per la stima del **Pulse Arrival Time (PAT)** e della pressione arteriosa a partire da segnali **ECG** e **PPG** acquisiti in tempo reale da due dispositivi Arduino (nRF52840) via Bluetooth Low Energy, con interfaccia grafica in Streamlit per gestione utenti, calibrazione, acquisizione misure e visualizzazione storico.

Progetto sviluppato per il corso di Laboratorio di Elettronica e Biosensori (Politecnico di Milano) — Gruppo 3.

## Struttura del progetto

```
lteb_PATproject/
├── interfaccia.py             # App Streamlit: login/registrazione, calibrazione,
│                               # acquisizione misure, storico, visualizzazione grafici
├── programma_background.py    # Script di supporto: connessione BLE, acquisizione e
│                               # pre-processing dei segnali ECG/PPG (scipy/numpy)
├── sinc4ECG.ino                # Firmware Arduino (nRF52840) per il modulo ECG (AD8232)
├── sinc4PPG.ino                # Firmware Arduino (nRF52840) per il modulo PPG (MAX3010x)
├── requirements.txt            # Dipendenze Python
├── Report/                     # Relazione di progetto (PDF + sorgenti LaTeX e immagini)
└── users.db                    # Database SQLite (creato/aggiornato automaticamente al primo avvio)
```

## Hardware

- 2x scheda Arduino nRF52840 (comunicazione BLE tramite UART service, libreria `bluefruit`)
- Modulo ECG basato su AD8232, campionamento a 512 Hz
- Modulo PPG basato su SparkFun Bio Sensor Hub (MAX3010x), campionamento a 256 Hz
- RTC SparkFun RV8803 su entrambi i moduli per il sincronismo temporale

I firmware (`sinc4ECG.ino`, `sinc4PPG.ino`) vanno caricati sulle rispettive schede tramite Arduino IDE, con le librerie `Adafruit_nRF52 (bluefruit)`, `SparkFun_RV8803` e `SparkFun_Bio_Sensor_Hub_Library` installate.

## Software — requisiti

- Python 3.10 o superiore (sviluppato e testato con Python 3.12)
- Le dipendenze Python sono elencate in `requirements.txt`

### Installazione

Si consiglia di lavorare in un virtual environment dedicato:

```bash
python3 -m venv venv
source venv/bin/activate      # su Windows: venv\Scripts\activate

pip install -r requirements.txt
```

> **Nota Bluetooth:** la libreria `bleak` richiede il Bluetooth attivo sul computer. Su Windows non serve configurazione aggiuntiva; su macOS assicurarsi di aver concesso i permessi Bluetooth al terminale/IDE; su Linux è generalmente richiesto BlueZ installato.

## Avvio dell'interfaccia

Con il virtual environment attivo, dalla cartella del progetto:

```bash
streamlit run interfaccia.py
```

L'applicazione si apre automaticamente nel browser (di default su `http://localhost:8501`). Al primo avvio viene creato in automatico il file `users.db` con lo schema necessario (utenti, dispositivi, calibrazioni, misure, campioni).

Il flusso applicativo previsto è:
1. Registrazione / login utente
2. Scelta o esecuzione di una calibrazione
3. Accensione e connessione BLE dei due dispositivi (ECG e PPG)
4. Acquisizione di una nuova misura in tempo reale
5. Salvataggio della misura con relativi metadati (data, periodo della giornata) e consultazione nello storico

## Report

La relazione completa di progetto (metodologia, schemi elettrici, elaborazione del segnale, risultati) si trova in `Report/Gruppo_3_Laboratorio_di_Elettronica_e_Biosensori.pdf`, con i sorgenti LaTeX nella cartella omonima.

## Note

- `requirements.txt` è stato ricostruito a partire dagli import effettivamente presenti nel codice (`interfaccia.py`, `programma_background.py`), poiché non era stato generato in fase di sviluppo. Verificare le versioni installate con `pip freeze > requirements-lock.txt` se si vuole congelare l'ambiente esatto usato per i test.
- Il file `users.db` contiene dati personali degli utenti (inclusa password hashata con bcrypt) ed è correttamente escluso dal repository — vedi `.gitignore`.
