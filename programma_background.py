import time
import sqlite3
import signal
import sys
import asyncio
import struct
import queue
import csv
import pandas as pd
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks
from datetime import datetime
from bleak import BleakScanner, BleakClient

running = True

def stop_handler(sig, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)

# --- QUEUE GLOBALE PER DB ---
db_queue = queue.Queue()

# --- CONFIGURAZIONE ---
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# Parametri Analisi
WINDOW_SECONDS = 6       
ANALYSIS_INTERVAL = 1.0  
FS_ECG = 512.0           
FS_PPG = 256.0         

# Calibrazione Pressione
CALIB_M_mean = -0.1083   
CALIB_Q_mean = 55.9162
CALIB_hr_mean = 1.6117

CALIB_M_diast = -0.1380   
CALIB_Q_diast = 117.6609 
CALIB_hr_diast = 0.3916

CALIB_M_sist = -0.0489
CALIB_Q_sist = -67.5732
CALIB_hr_sist = 4.0518

# --- DATABASE MANAGER ---
class DatabaseManager:
    """ 
    Simula l'interfaccia verso il Database.
    """
    def __init__(self):
        self.conn = sqlite3.connect(
            "users.db",
            check_same_thread=False,
            timeout=30
        )
        self.cur = self.conn.cursor()

    def insert_valori_misura(self, record):
        self.cur.execute("""
            INSERT INTO valori_misura (
                timestamp_ecg,
                ampiezza_ecg,
                timestamp_ppg,
                ampiezza_ppg
            ) VALUES (?, ?, ?, ?)
        """, (
            record.get("timestamp_ecg"),
            record.get("ampiezza_ecg"),
            record.get("timestamp_ppg"),
            record.get("ampiezza_ppg")
        ))
        self.conn.commit()

    def insert_indici_misura(self, record):
        self.cur.execute("""
            INSERT INTO indici_misura (
                timestamp_pressione,
                pressione_calcolata_media,
                pressione_calcolata_diast,
                pressione_calcolata_sist,
                timestamp_hr,
                hr
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record["timestamp_pressione"],
            record["pressione_calcolata_media"],
            record["pressione_calcolata_diast"],
            record["pressione_calcolata_sist"],
            record["timestamp_hr"],
            record["hr"]
        ))
        self.conn.commit()

    def close(self):
        self.conn.close()

db = DatabaseManager()

# --- 1. FUNZIONI DI ELABORAZIONE SEGNALE ---
def process_ecg_algo(timestamps, values, fs):
    if len(values) < fs * 1: return []
    signal_raw = np.array(values)
    nyq = 0.5 * fs
    b, a = butter(1, [5/nyq, 15/nyq], btype='band')
    signal_bandpass = filtfilt(b, a, signal_raw - np.mean(signal_raw))
    signal_diff = np.diff(signal_bandpass, prepend=signal_bandpass[0])
    signal_sq = signal_diff ** 2
    w_samples = int(0.150 * fs)
    signal_integrated = np.convolve(signal_sq, np.ones(w_samples)/w_samples, mode='same')
    threshold = np.mean(signal_integrated) * 2
    min_dist = int(0.25 * fs) 
    peaks_integrated, _ = find_peaks(signal_integrated, distance=min_dist, height=threshold)
    search_window = int(0.1 * fs)
    final_peaks_data = []
    for p in peaks_integrated:
        start_s = max(0, p - search_window)
        end_s = min(len(signal_raw), p + search_window)
        local_max_idx = np.argmax(signal_raw[start_s:end_s]) + start_s
        final_peaks_data.append((timestamps[local_max_idx], signal_raw[local_max_idx]))
    return final_peaks_data

def process_ppg_algo(timestamps, values, fs):
    if len(values) < fs * 2: return []
    df = pd.DataFrame({'Valore': values})
    window_size = int(0.75 * fs) | 1 
    df['Baseline'] = df['Valore'].rolling(window=window_size, center=True).mean().bfill().ffill()
    df['AC_Signal'] = df['Valore'] - df['Baseline']
    nyq = 0.5 * fs
    b, a = butter(4, 5.0 / nyq, btype='low', analog=False)
    try:
        df['AC_Filtered'] = filtfilt(b, a, df['AC_Signal'])
    except: return [] 
    std_window = int(2 * fs) | 1
    df['Rolling_Std'] = df['AC_Filtered'].rolling(window=std_window, center=True).std().bfill().ffill()
    df['Z_Score'] = df['AC_Filtered'] / (df['Rolling_Std'] + 1e-6)
    z_inverted = -df['Z_Score'].fillna(0).values
    min_dist = int(0.40 * fs) 
    peaks_smooth_indices, _ = find_peaks(z_inverted, distance=min_dist, prominence=0.6, height=0.9)
    final_feet_data = []
    search_window = int(0.1 * fs) 
    for p_idx in peaks_smooth_indices:
        start_s = max(0, p_idx - search_window)
        end_s = min(len(values), p_idx + search_window)
        segment = values[start_s:end_s]
        local_min_rel = np.argmin(segment) 
        refined_idx = start_s + local_min_rel
        final_feet_data.append((timestamps[refined_idx], values[refined_idx]))
    return final_feet_data

# --- 2. GESTORE DISPOSITIVO ---
class DeviceHandler:
    # Buffer globale temporaneo per combinare ECG + PPG
    pending_measure = {}

    def __init__(self, name, device_type, fs, algorithm_func):
        self.name = name
        self.type = device_type # 'ECG' o 'PPG'
        self.fs = fs
        self.algo_func = algorithm_func 
        self.client = None
        self.is_connected = False
        
        self.buffer_timestamps = [] 
        self.buffer_values = []     
        self.last_detected_tick = 0 
        
        self.current_block_timestamp = 0
        self.sample_counter_in_block = 0

    async def notification_handler(self, sender, data):
        if len(data) == 4: 
            self.current_block_timestamp = struct.unpack('<I', data)[0]
            self.sample_counter_in_block = 0
        else: 
            try:
                for value_tuple in struct.iter_unpack('<H', data):
                    val = value_tuple[0]
                    abs_tick = self.current_block_timestamp + self.sample_counter_in_block

                    # --- AGGIORNA BUFFER GLOBALE PER SINCRONIZZARE ---
                    if abs_tick not in DeviceHandler.pending_measure:
                        DeviceHandler.pending_measure[abs_tick] = {
                            'timestamp_ecg': None,
                            'ampiezza_ecg': None,
                            'timestamp_ppg': None,
                            'ampiezza_ppg': None
                        }

                    record = DeviceHandler.pending_measure[abs_tick]

                    if self.type == 'ECG':
                        record['timestamp_ecg'] = abs_tick
                        record['ampiezza_ecg'] = val
                    elif self.type == 'PPG':
                        record['timestamp_ppg'] = abs_tick
                        record['ampiezza_ppg'] = val

                    # Se entrambi i valori sono presenti, metti in queue per DB
                    if record['ampiezza_ecg'] is not None and record['ampiezza_ppg'] is not None:
                        db_queue.put(record.copy())
                        del DeviceHandler.pending_measure[abs_tick]

                    # Buffer per analisi
                    self.buffer_timestamps.append(abs_tick)
                    self.buffer_values.append(val)
                    self.sample_counter_in_block += 1
            except struct.error:
                pass

    def get_new_events(self):
        max_samples = int(self.fs * 6)
        if len(self.buffer_values) > max_samples:
            self.buffer_timestamps = self.buffer_timestamps[-max_samples:]
            self.buffer_values = self.buffer_values[-max_samples:]
        
        if len(self.buffer_values) < self.fs * 2: return []

        found_points = self.algo_func(self.buffer_timestamps, self.buffer_values, self.fs)
        new_points = [p for p in found_points if p[0] > self.last_detected_tick]
        
        if new_points:
            self.last_detected_tick = new_points[-1][0]
            points_in_ms = []
            for tick, val in new_points:
                time_ms = (tick / self.fs) * 1000.0
                points_in_ms.append({'tick': tick, 'time_ms': time_ms, 'val': val})
            return points_in_ms
        return []

    async def connect(self):
        print(f"🔍 Cercando {self.name}...")
        from bleak import BleakScanner, BleakClient
        device = await BleakScanner.find_device_by_filter(lambda d, ad: d.name and d.name == self.name)
        if not device:
            print(f"❌ {self.name} non trovato.")
            return False
        try:
            self.client = BleakClient(device)
            await self.client.connect()
            self.is_connected = True
            print(f"✅ Connesso a {self.name}")
            await self.client.start_notify("6E400003-B5A3-F393-E0A9-E50E24DCCA9E", self.notification_handler)
            return True
        except Exception as e:
            print(f"❌ Errore {self.name}: {e}")
            return False

    async def send_start(self):
        if self.is_connected:
            await self.client.write_gatt_char("6E400002-B5A3-F393-E0A9-E50E24DCCA9E", b'S')

    async def disconnect(self):
        if self.is_connected:
            await self.client.disconnect()

# --- 3. LOGICA PAT ---
def calculate_pat_logic(pending_ecg, available_ppg):
    pat_results = []
    unmatched_ecg = []
    pending_ecg.sort(key=lambda x: x['time_ms'])
    available_ppg.sort(key=lambda x: x['time_ms'])

    ppg_idx = 0
    for ecg in pending_ecg:
        matched = False
        while ppg_idx < len(available_ppg):
            ppg = available_ppg[ppg_idx]
            if ppg['time_ms'] > ecg['time_ms']:
                dt = ppg['time_ms'] - ecg['time_ms']
                if dt < 1500: 
                    pat_results.append({
                        'ecg_time': ecg['time_ms'],
                        'ppg_time': ppg['time_ms'],
                        'pat_ms': dt
                    })
                    matched = True
                    ppg_idx += 1 
                    break
                else: break
            else: ppg_idx += 1
        if not matched: unmatched_ecg.append(ecg)
            
    return pat_results, unmatched_ecg, available_ppg[ppg_idx:]

# --- 4. ACQUISIZZIONE PARAMETRI REGRESSIONE ---
def get_calibrazione(misura_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""
        SELECT
            CALIB_M_mean,
            CALIB_Q_mean,
            CALIB_hr_mean,
            CALIB_M_diast,
            CALIB_Q_diast,
            CALIB_hr_diast,
            CALIB_M_sist,
            CALIB_Q_sist,
            CALIB_hr_sist
        FROM calibrazioni
        WHERE nome_calibrazione = ?
    """, (misura_id,))
    row = c.fetchone()
    conn.close()

    return (
        row[0],  # CALIB_M_mean
        row[1],  # CALIB_Q_mean
        row[2],  # CALIB_hr_mean
        row[3],  # CALIB_M_diast
        row[4],  # CALIB_Q_diast
        row[5],  # CALIB_hr_diast
        row[6],  # CALIB_M_sist
        row[7],  # CALIB_Q_sist
        row[8],  # CALIB_hr_sist
    )


# --- 4. LOOP PRINCIPALE ---
async def main():
    handler_ppg = DeviceHandler("boardPPG", "PPG", 256.0, process_ppg_algo)
    handler_ecg = DeviceHandler("boardECG", "ECG", 512.0, process_ecg_algo)

    print("--- CONNESSIONE ---")
    await asyncio.gather(handler_ppg.connect(), handler_ecg.connect(), return_exceptions=True)

    if not handler_ppg.is_connected and not handler_ecg.is_connected:
        db.close()
        return

    print("⏳ Stabilizzazione...")
    await asyncio.sleep(2)
    print("--- START ---")
    await asyncio.gather(handler_ppg.send_start(), handler_ecg.send_start(), return_exceptions=True)
    
    pending_ecg_peaks = []
    pending_ppg_feet = []

    # misura_id = int(sys.argv[1])
    # CALIB_M_mean, CALIB_Q_mean, CALIB_hr_mean, CALIB_M_diast, CALIB_Q_diast, CALIB_hr_diast, CALIB_M_sist, CALIB_Q_sist, CALIB_hr_sist = get_calibrazione(misura_id)

    try:
        last_analysis_time = 0
        current_bpm = 0.0 
        loop = asyncio.get_running_loop()
        
        while running:
            now = loop.time()

            # --- SCRITTURA DB DA QUEUE ---
            while not db_queue.empty():
                record = db_queue.get()
                db.insert_valori_misura(record)

            # --- ANALISI PAT ---
            if now - last_analysis_time > 1.0:
                new_ecg = handler_ecg.get_new_events() if handler_ecg.is_connected else []
                new_ppg = handler_ppg.get_new_events() if handler_ppg.is_connected else []

                if new_ecg: 
                    pending_ecg_peaks.extend(new_ecg)
                    if len(pending_ecg_peaks) >= 2:
                        rr_ms = pending_ecg_peaks[-1]['time_ms'] - pending_ecg_peaks[-2]['time_ms']
                        if rr_ms > 0: current_bpm = 60000.0 / rr_ms

                if new_ppg: pending_ppg_feet.extend(new_ppg)

                if pending_ecg_peaks and pending_ppg_feet:
                    pats, remaining_ecg, remaining_ppg = calculate_pat_logic(pending_ecg_peaks, pending_ppg_feet)
                    pending_ecg_peaks = remaining_ecg
                    pending_ppg_feet = remaining_ppg
                    
                    if pats:
                        for p in pats:
                            pat_val = p['pat_ms']
                            estimated_bp_mean = (CALIB_M_mean * pat_val) + CALIB_Q_mean + (CALIB_hr_mean * current_bpm)
                            estimated_bp_diast = (CALIB_M_diast * pat_val) + CALIB_Q_diast + (CALIB_hr_diast * current_bpm)
                            estimated_bp_sist = (CALIB_M_sist * pat_val) + CALIB_Q_sist + (CALIB_hr_sist * current_bpm)

                            indici_misura = {
                                'timestamp_pressione': p['ecg_time'],
                                'pressione_calcolata_media': estimated_bp_mean,
                                'pressione_calcolata_diast': estimated_bp_diast,
                                'pressione_calcolata_sist': estimated_bp_sist,
                                'timestamp_hr': p['ecg_time'],
                                'hr': current_bpm
                            }
                            db.insert_indici_misura(indici_misura)

                last_analysis_time = now

            await asyncio.sleep(0.05)

    except KeyboardInterrupt:
        print("\n🛑 Stop utente.")
    finally:
        await handler_ppg.disconnect()
        await handler_ecg.disconnect()
        db.close()
        print("✅ Finito.")

if __name__ == "__main__":
    asyncio.run(main())
