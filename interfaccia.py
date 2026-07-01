import streamlit as st
import pickle
import os
import pandas as pd
import warnings
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
import streamlit.components.v1 as components
import base64
import sqlite3
import bcrypt
import io
from PIL import Image, ImageOps, ImageDraw
from streamlit_option_menu import option_menu
from streamlit_pills import pills
from bleak import BleakScanner, BleakClient
import asyncio
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh
import plotly.express as px
import streamlit_shadcn_ui as ui
import nest_asyncio
import subprocess
import struct
import time
nest_asyncio.apply()

# --- CONFIGURAZIONE ---
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# Parametri Analisi
WINDOW_SECONDS = 6       
ANALYSIS_INTERVAL = 1.0  
FS_ECG = 512.0           
FS_PPG = 256.0   

# Directory 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#----------------Funzinoni session.stage-----------------------
# Funzione per cambiare pagina
def go_to(page_name):
    st.session_state.page = page_name

def Scelta_calibrazione(scelta):
    st.session_state["calibrazione_scelta"] = scelta
    st.session_state["calibrazione_da_tenere_fine_misura"] = scelta
    st.session_state["sel_calibrazione"] = True

# IN TEORIA QUESTA NON SERVE PIù
# def Selezione_calibrazione(scelta):
#     if scelta==0:
#         st.session_state.selezione_calibrazione = False
#     elif scelta==1:
#         st.session_state.selezione_calibrazione = True
#     else:
#         del st.session_state.selezione_calibrazione


# ------------------------------ Funzioni Database --------------------------------
def init_db():
    
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, 
            nome TEXT NOT NULL,
            cognome TEXT NOT NULL,
            data_nascita DATE NOT NULL,
            sesso TEXT CHECK(sesso IN ('M', 'F')) NOT NULL,
            peso REAL NOT NULL, 
            altezza REAL NOT NULL,
            telefono TEXT UNIQUE NOT NULL,
            ice TEXT NOT NULL,
            profile_pic BLOB
        )
    """)
    conn.commit()
    conn.close()

    #conn = sqlite3.connect("users.db")
    #c = conn.cursor()
    #c.execute("""
    #    CREATE TABLE IF NOT EXISTS misure (
    #        id_misura INTEGER PRIMARY KEY AUTOINCREMENT,
    #        username TEXT UNIQUE NOT NULL,
    #        data_misura DATE,
    #        periodo_giornata TEXT NOT NULL
    #        )
    #""")
    #conn.commit()
    #conn.close()

    #conn = sqlite3.connect("users.db")
    #c = conn.cursor()
    #c.execute("""
    #    CREATE TABLE IF NOT EXISTS campione (
    #        id_campione INTEGER PRIMARY KEY AUTOINCREMENT,
    #        id_misura INTEGER NOT NULL,
    #        indice_campione INTEGER NOT NULL,
    #        pressione_campione REAL NOT NULL
    #        )
    #""")
    #conn.commit()
    #conn.close()
    
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS dispositivi (
            id_dispositivo INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_dispositivo TEXT NOT NULL,
            segnale_misurato INTEGER NOT NULL,    -- 0 = ECG, 1 = altro...
            path_foto_dispositivo TEXT
        )
    """)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS calibrazioni (
            id_calibrazione INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_calibrazione TEXT NOT NULL,
            utente_calibrazione TEXT NOT NULL,
            CALIB_M_mean REAL NOT NULL,
            CALIB_Q_mean REAL NOT NULL,
            CALIB_hr_mean REAL NOT NULL,
            CALIB_M_diast REAL NOT NULL,
            CALIB_Q_diast REAL NOT NULL,
            CALIB_hr_diast REAL NOT NULL,
            CALIB_M_sist REAL NOT NULL,
            CALIB_Q_sist REAL NOT NULL,
            CALIB_hr_sist REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS misure (
            id_misura INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo_giornata TEXT,
            data_misura DATE,
            calibrazione TEXT,
            username TEXT NOT NULL,
            FOREIGN KEY(username) REFERENCES users(username)
        )
    """)
    #c.execute("""DROP TABLE IF EXISTS campioni""")  # per evitare duplicati in fase di sviluppo, altrimenti commentare
    c.execute("""
        CREATE TABLE IF NOT EXISTS campioni (
            id_campione INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo_campione TEXT,
            ampiezza_campione REAL,
            timestamp_campione DATETIME,
            id_misura INTEGER,
            FOREIGN KEY(id_misura) REFERENCES misure(id_misura)
        )
    """)

    #c.execute("""DROP TABLE IF EXISTS valori_misura""")  # per evitare duplicati in fase di sviluppo, altrimenti commentare
    c.execute("""
        CREATE TABLE IF NOT EXISTS valori_misura (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ecg DATETIME,
            ampiezza_ecg REAL,
            timestamp_ppg DATETIME,
            ampiezza_ppg REAL
        )
    """)

    #c.execute("""DROP TABLE IF EXISTS indici_misura""")  # per evitare duplicati in fase di sviluppo, altrimenti commentare
    c.execute("""
        CREATE TABLE IF NOT EXISTS indici_misura (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_pressione DATETIME,
            pressione_calcolata_media REAL,
            pressione_calcolata_diast REAL,
            pressione_calcolata_sist REAL,
            timestamp_hr DATETIME,
            hr REAL
        )
    """)

    conn.commit()
    conn.close()

def register_user(username, password, nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        c.execute("INSERT INTO users (username, password_hash, nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice) VALUES (?,?,?,?,?,?,?,?,?,?)", (username, hashed, nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def authenticate_user(username, password):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return bcrypt.checkpw(password.encode(), row[0])
    return False

def get_user_data(username):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        SELECT nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice, profile_pic
        FROM users 
        WHERE username=?
    """, (username,))
    row = c.fetchone()
    conn.close()
    return row if row else None

def update_user_data(username, peso, altezza):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        UPDATE users 
        SET peso=?, altezza=?
        WHERE username=?
    """, (peso, altezza, username))
    conn.commit()
    conn.close()

def update_user_contacts(username, telefono, ice):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        UPDATE users 
        SET telefono=?, ice=?
        WHERE username=?
    """, (telefono, ice, username))
    conn.commit()
    conn.close()

def update_password(username, new_password):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
    c.execute("""
        UPDATE users
        SET password_hash=?
        WHERE username=?
    """, (hashed, username))
    conn.commit()
    conn.close()

def update_user_pic(username, pic_data):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        UPDATE users
        SET profile_pic=?
        WHERE username=?
    """, (pic_data, username))
    conn.commit()
    conn.close()


def get_misure_in_range(username, start_date):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    # prendo tutte le sessioni dell'utente nel range
    c.execute(
        """
        SELECT data_misura, id_misura, periodo_giornata
        FROM misure
        WHERE username = ?
        AND data_misura >= ?
        ORDER BY data_misura DESC
        """,
        (username, start_date),
    )
    rows = c.fetchall()

    dati = []
    for data_misura, id_misura, periodo_giornata in rows:
        # prendo tutti i valori di pressione per questa misura
        c = conn.cursor()
        c.execute(
            """
            SELECT ampiezza_campione, tipo_campione
            FROM campioni
            WHERE id_misura = ?
            """,
            (id_misura,),
        )
        data = c.fetchall()
        segnali = {
            "ECG": [],
            "PPG": [],
            "Pressione": [],
            "Pressione_sist": [],
            "Pressione_diast": [],
            "HR": []
        }
        for amp, tipo in data:
            if tipo in segnali:
                segnali[tipo].append(amp)

        pressioni = segnali["Pressione"]
        if pressioni:
            media = sum(pressioni) / len(pressioni)
        else:
            media = None

        pressioni1 = segnali["Pressione_sist"]
        if pressioni1:
            media2 = sum(pressioni1) / len(pressioni1)
        else:
            media2 = None

        pressioni2 = segnali["Pressione_diast"]
        if pressioni2:
            media3 = sum(pressioni2) / len(pressioni2)
        else:
            media3 = None

        frequenze = segnali["HR"]
        if frequenze:
            media1 = sum(frequenze) / len(frequenze)
        else:
            media1 = None

        dati.append({
            "data_misura": data_misura,
            "id_misura": id_misura,
            "periodo_giornata": periodo_giornata,
            "media_pressione": media,
            "media_pressione_diast": media3,
            "media_pressione_sist": media2,
            "media_frequenze": media1,

        })

    conn.close()
    df = pd.DataFrame(dati)
    return df


def get_start_date(option):
    today = datetime.now()
    if option == "Ultima settimana":
        return today - timedelta(days=7)
    elif option == "Ultimo mese":
        return today - timedelta(days=30)
    elif option == "Ultimi 3 mesi":
        return today - timedelta(days=90)
    else:
        return datetime(1970, 1, 1)

def get_misure_user(username):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        SELECT m.id_misura, m.data_misura 
        FROM misure m
        WHERE m.username=? 
          AND EXISTS (SELECT 1 FROM campioni c WHERE c.id_misura = m.id_misura)
        ORDER BY m.data_misura DESC
    """, (username,))
    rows = c.fetchall()
    conn.close()
    return rows  # ritorna lista di tuple [(id, data_ora), ...]

def get_misura_by_id(misura_id):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("SELECT data_misura FROM misure WHERE id_misura=?", (misura_id,))
    row = c.fetchone()

    c = conn.cursor()
    c.execute("SELECT periodo_giornata FROM misure WHERE id_misura=?", (misura_id,))
    periodo = c.fetchone()

    c = conn.cursor()
    c.execute("SELECT calibrazione FROM misure WHERE id_misura=?", (misura_id,))
    calibrazione = c.fetchone()

    # c = conn.cursor()
    # c.execute("SELECT calibrazione FROM misure WHERE id_misura=?", (misura_id,))
    # calibrazionen = c.fetchone()
    # conn.close()

    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("SELECT tipo_campione, ampiezza_campione, timestamp_campione FROM campioni WHERE id_misura=?", (misura_id,))
    rows = c.fetchall()
    conn.close()
    segnali = {
        "ECG": {"amp": [], "ts": []},
        "PPG": {"amp": [], "ts": []},
        "Pressione": {"amp": [], "ts": []},
        "Pressione_diast": {"amp": [], "ts": []},
        "Pressione_sist": {"amp": [], "ts": []},
        "HR": {"amp": [], "ts": []},
    }
    for tipo, amp, ts in rows:
        if tipo in segnali:
            segnali[tipo]["amp"].append(amp)
            segnali[tipo]["ts"].append(ts)
    
    return row, periodo, calibrazione, segnali

def plot_andamento(dataframe, titolo):
    fig, ax = plt.subplots()

    ax.plot(
        dataframe["data_ora"],
        dataframe["media_pressione"],
        marker="o",
        linestyle="-"
    )
    
    ax.set_title(titolo)
    ax.set_xlabel("Data")
    ax.set_ylabel("Pressione media (mmHg)")
    ax.grid(True)

    st.pyplot(fig)

def plot_andamento_frequenza(dataframe, titolo):
    fig, ax = plt.subplots()

    ax.plot(
        dataframe["data_ora"],
        dataframe["media_frequenze"],
        marker="*",
        linestyle="-"
    )
    
    ax.set_title(titolo)
    ax.set_xlabel("Data")
    ax.set_ylabel("Frequenza cardiaca media (bpm)")
    ax.grid(True)

    st.pyplot(fig)

def get_valori_misura():
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    df = pd.read_sql_query("""
        SELECT timestamp_ecg, ampiezza_ecg, 
               timestamp_ppg, ampiezza_ppg
        FROM valori_misura
    """, conn)
    conn.close()
    if not df.empty:
        df["timestamp_ecg"] = pd.to_datetime(df["timestamp_ecg"])
        df["timestamp_ppg"] = pd.to_datetime(df["timestamp_ppg"])
    return df

def get_indici_misura():
    if "ultimo_timestamp_indici" not in st.session_state:
        st.session_state.ultimo_timestamp_indici = None

    last_timestamp_old = st.session_state.ultimo_timestamp_indici or 0

    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    df = pd.read_sql_query("""
        SELECT timestamp_pressione, pressione_calcolata_media, pressione_calcolata_sist, pressione_calcolata_diast, 
               timestamp_hr, hr
        FROM indici_misura
    """, conn)
    conn.close()

    if df.empty:
        return df, last_timestamp_old

    df["timestamp_pressione"] = pd.to_datetime(df["timestamp_pressione"], errors="coerce")
    df["timestamp_hr"] = pd.to_datetime(df["timestamp_hr"], errors="coerce")

    # timestamp globale unico
    ts_press_max = df["timestamp_pressione"].max()
    ts_hr_max = df["timestamp_hr"].max()
    st.session_state.ultimo_timestamp_indici = max(ts_press_max, ts_hr_max)

    return df, last_timestamp_old

def finestra_temporale(df, col_timestamp, secondi=10):
    """Restituisce solo gli ultimi X secondi del DataFrame."""
    if df.empty:
        return df
    df[col_timestamp] = pd.to_datetime(df[col_timestamp])
    t_max = df[col_timestamp].max()
    t_min = t_max - pd.Timedelta(seconds=secondi)
    # filtro
    return df[df[col_timestamp] >= t_min]

# Inizializza il database all'avvio
init_db()


def get_tutti_indici_misura():
    """
    Restituisce l'intera tabella indici_misura con:
    - timestamp_pressione
    - pressione_calcolata
    - timestamp_hr
    - hr
    """
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    df = pd.read_sql_query("""
        SELECT timestamp_pressione, pressione_calcolata_media, pressione_calcolata_sist, pressione_calcolata_diast, 
               timestamp_hr, hr
        FROM indici_misura
    """, conn)
    conn.close()

    if not df.empty:
        # Convertiamo le colonne timestamp in datetime
        df["timestamp_pressione"] = pd.to_datetime(df["timestamp_pressione"], errors="coerce")
        df["timestamp_hr"] = pd.to_datetime(df["timestamp_hr"], errors="coerce")

    return df


def inserisci_misura(periodo_giornata, data_misura, user, calibrazione):
    #Calibrazione_in_uso = st.session_state.get("calibrazione_scelta", None)
    if "calibrazione_scelta" in st.session_state:
        del st.session_state.calibrazione_scelta
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO misure (periodo_giornata, data_misura, calibrazione, username)
        VALUES (?, ?, ?, ?)
    """, (periodo_giornata, data_misura, calibrazione, user))
    id_misure = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return id_misure

def inserisci_campioni(campioni_list, id_misure):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    cursor = conn.cursor()
    for campione in campioni_list:
        cursor.execute("""
            INSERT INTO campioni (tipo_campione, ampiezza_campione, timestamp_campione, id_misura)
            VALUES (?, ?, ?, ?)
        """, (
            campione["tipo_campione"], 
            campione["ampiezza_campione"], 
            campione["timestamp_campione"].isoformat(), 
            id_misure
        ))
    
    conn.commit()
    conn.close()

def crea_campioni_list(df_ecg, df_ppg, df_pressione, df_hr, df_pressione_sist, df_pressione_diast):
    campioni_list = []

    # ECG
    if not df_ecg.empty:
        for _, row in df_ecg.iterrows():
            campioni_list.append({
                "tipo_campione": "ECG",
                "ampiezza_campione": row["ampiezza_ecg"],
                "timestamp_campione": row["timestamp_ecg"]
            })

    # PPG
    if not df_ppg.empty:
        for _, row in df_ppg.iterrows():
            campioni_list.append({
                "tipo_campione": "PPG",
                "ampiezza_campione": row["ampiezza_ppg"],
                "timestamp_campione": row["timestamp_ppg"]
            })

    # Pressione
    if not df_pressione.empty:
        for _, row in df_pressione.iterrows():
            campioni_list.append({
                "tipo_campione": "Pressione",
                "ampiezza_campione": row["pressione_calcolata_media"],
                "timestamp_campione": row["timestamp_pressione"]
            })

    if not df_pressione_sist.empty:
        for _, row in df_pressione_sist.iterrows():
            campioni_list.append({
                "tipo_campione": "Pressione_sist",
                "ampiezza_campione": row["pressione_calcolata_sist"],
                "timestamp_campione": row["timestamp_pressione"]
            })

    if not df_pressione_diast.empty:
        for _, row in df_pressione_diast.iterrows():
            campioni_list.append({
                "tipo_campione": "Pressione_diast",
                "ampiezza_campione": row["pressione_calcolata_diast"],
                "timestamp_campione": row["timestamp_pressione"]
            })

    # HR
    if not df_hr.empty:
        for _, row in df_hr.iterrows():
            campioni_list.append({
                "tipo_campione": "HR",
                "ampiezza_campione": row["hr"],
                "timestamp_campione": row["timestamp_hr"]
            })

    return campioni_list

def reset_valori_misura():
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("DELETE FROM valori_misura")
    c.execute("DELETE FROM indici_misura")
    conn.commit()
    conn.close()

def salva_misura(data_misura, periodo_giornata, lista, user, calibrazione):
    id_misura = inserisci_misura(periodo_giornata, data_misura, user, calibrazione)
    inserisci_campioni(lista, id_misura)
    go_to("storico")
    
def scala_tempo(df, col_ts, fattore=1000):
    if df.empty:
        return pd.Series(dtype=float)
    t0 = pd.to_datetime(df[col_ts].iloc[0])
    t_sec = (pd.to_datetime(df[col_ts]) - t0).dt.total_seconds()
    return t_sec * fattore

def df_da_segnali(segnali, tipo, fattore=1000):
    ts_list = segnali[tipo]["ts"]
    amp_list = segnali[tipo]["amp"]
    if not ts_list or not amp_list:
        return pd.DataFrame(columns=["ts", "amp", "t_scaled"])
    df = pd.DataFrame({
        "ts": pd.to_datetime(ts_list),
        "amp": amp_list
    })

    df["t_scaled"] = scala_tempo(df, "ts", fattore)
    return df

def get_informazioni_utenti(new_username, cellulare):
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    c = conn.cursor()
    c.execute("""
        SELECT username, telefono
        FROM users
    """)
    rows = c.fetchall()
    conn.close()
    usernames = {u.strip().lower() for u, _ in rows}
    telefoni = {t.strip() for _, t in rows}
    if new_username.strip().lower() in usernames:
        st.error("Username già in uso")
    elif cellulare.strip() in telefoni:
        st.error("Numero di telefono già in uso")


#----------------Configurazione generale-----------------------
# === Pagina wide ===
st.set_page_config(
    page_title="Monitoraggio Pressione",
    page_icon="🩺",   # Emoji come icona, ma posso mettere anche un'immagine 
    layout="wide"
)

warnings.filterwarnings("ignore")

# Inizializza la pagina se non esiste
if "page" not in st.session_state:
    st.session_state.page = "None"

# Inizializza session_state
if "menu_open" not in st.session_state:
    st.session_state.menu_open = False # altrimenti si apre sempre e subito

if "show_modal" not in st.session_state:
    st.session_state.show_modal = False

if "sono_passato_da_calibrazione" not in st.session_state:
    st.session_state.sono_passato_da_calibrazione = False

if "sono_passato_da_AvvioMisura" not in st.session_state:
    st.session_state.sono_passato_da_AvvioMisura = False

if "trovato" not in st.session_state:
    st.session_state.trovato = None

if "connected" not in st.session_state:
    st.session_state.connected = None

if "ricerca_avviata" not in st.session_state:
    st.session_state.ricerca_avviata = False

if "tentativo_connessione" not in st.session_state:
    st.session_state.tentativo_connessione = False

if "worker_process" not in st.session_state:
    st.session_state.worker_process = None

if "avanti_enabled" not in st.session_state:
    st.session_state.avanti_enabled = False

if "scelta" not in st.session_state:
    st.session_state.scelta = ""

if "calibrazione_scelta" not in st.session_state:
    st.session_state.calibrazione_scelta = None


# === Stile CSS personalizzato ===
st.markdown("""
    <style>
    /* ---------- Generale ---------- */
    h1, h2, h3 {
        text-align: center;
    }
    p {
        text-align: center;
        font-size: 16px;
        /*color: #555555;*/
    }

    /* ---------- Bottoni generali ---------- */
    button[kind="primary"], .stButton>button {
        background-color: #4da6ff !important;
        color: white !important;
        -webkit-text-fill-color: #ffffff !important;
        width: 100% !important;
        height: 40px !important;
        font-size: 16px !important;
        border-radius: 8px !important;
        border: 2px solid #4da6ff !important;
    }
    button[kind="primary"]:hover {
        background-color: #3399ff !important;
        border-color: #3399ff !important;
        color: white !important;
    }
    div.stButton > button:focus {
        border-color: #3399ff;
        outline: none;
    }

    /* ---------- Menu laterale ---------- */
    .option-menu .menu-title {
        font-family: 'Inter', sans-serif !important;
        font-size: 16px !important;
        font-weight: 600 !important;
        color: black !important;
        display: flex !important;
        align-items: center !important;    /* centra verticalmente */
        padding-left: 0px !important; /* allineamento con i bottoni */
    }
    .option-menu .nav-link, .option-menu .nav-link-selected {
        font-family: 'Inter', sans-serif !important;
        font-size: 16px !important;
        text-align: left !important;
        width: 100% !important;
        padding: 10px 8px !important;
        border-radius: 6px !important;
    }
    .option-menu .nav-link:hover {
        background-color: rgba(0,0,0,0.05) !important;
    }
    .option-menu .nav-link-selected {
        background-color: #4da6ff !important;
        color: white !important;
    }

    /* ---------- Avatar ---------- */
    .avatar-mask-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .avatar-mask {
        width: 150px !important;
        height: 150px !important;
        border-radius: 50% !important;
        background-color: black;
        -webkit-mask-repeat: no-repeat !important;
        -webkit-mask-position: center !important;
        -webkit-mask-size: contain !important;
        -webkit-mask-image: url("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg") !important;
        mask-repeat: no-repeat !important;
        mask-position: center !important;
        mask-size: contain !important;
        mask-image: url("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg") !important;
        display: inline-block;
    }
    @media (prefers-color-scheme: dark) {
        .avatar-mask {
            background-color: white !important;
        }
    }

    /* ---------- Main ---------- */
    .main {
        background-color: #f9fafb;
    }
    .stSubheader, h2, h3 {
        color: #333;
    }

    /* ---------- Card ---------- */
    .card {
        background-color: white;
        padding: 1.5rem;
        border-radius: 0.8rem;
        box-shadow: 0 0 10px rgba(0,0,0,0.05);
        margin-bottom: 1.5rem;
    }

    /* ---------- Device container ---------- */
    .device-container img {
        width: 80px !important;
        height: auto !important;
        object-fit: contain !important;
        display: block;
        margin: 0 auto;
    }
    </style>
""", unsafe_allow_html=True)
#img = "/Users/Giorgia/Downloads/caramella_sfondo_trasparente.png"
#img = "https://upload.wikimedia.org/wikipedia/commons/thumb/0/02/Sparkfun_logo.svg/640px-Sparkfun_logo.svg.png"
img = "https://i.kickstarter.com/photos/237/sparkfunlogo_kickstarter.full.original.jpg?anim=false&fit=crop&height=220&origin=ugc&q=92&width=220&sig=mqR3Av84F7RjnVRUf7JlEpX%2Byk031iaS542%2Bc2JKYT0%3D"
lista_dispositivi_ECG = [
    {"nome": "Sensore_ECG A", "img": img},
    {"nome": "Sensore_ECG B", "img": img},
    {"nome": "Sensore_ECG C", "img": img},
]
lista_dispositivi_PPG = [
    {"nome": "Sensore_PPG A", "img": img},
    {"nome": "Sensore_PPG B", "img": img},
    {"nome": "Sensore_PPG C", "img": img},
]

calibrazioni = ["Andrea", "Matteo", "Anna", "Fabiola", "Giorgia"]
#calibrazioni = [" "] + calibrazioni

# ------------- MENU LATERALE --------------
# Imposta un valore default se non esiste
if "menu_key" not in st.session_state:
    st.session_state["menu_key"] = "Home"

if st.session_state.menu_open:
    with st.sidebar:
        
        # Se è stato premuto il tasto "Annulla" nella pagina logout
        if st.session_state.get("go_home"):
            st.session_state["menu_key"] = "Home"
            st.session_state.page = "home"
            st.session_state["go_home"] = False

        # Se è stato premuto il tasto "Nuova Misura" nella home
        if st.session_state.get("go_misura"):
            st.session_state["menu_key"] = "Predizione"
            st.session_state.page = "predizione"
            st.session_state["go_misura"] = False

        # Se è stato premuto il tasto "Storico" nella home
        if st.session_state.get("go_storico"):
            st.session_state["menu_key"] = "Storico"
            st.session_state.page = "storico"
            st.session_state["go_storico"] = False

        calibrazione = False
        # Se è stato premuto il tasto "Calibrazione" nella pagina nuova misura
        if st.session_state.get("go_calibrazione"):
            st.session_state["menu_key"] = "Predizione"
            calibrazione = True
            st.session_state["go_calibrazione"] = False
        
        if st.session_state.get("sel_calibrazione"):
            st.session_state["menu_key"] = "Predizione"
            calibrazione = True
            st.session_state["sel_calibrazione"] = False

        if st.session_state.menu_key == "Predizione" and st.session_state.get("kanaries"):
            st.session_state["menu_key"] = "Predizione"
            calibrazione = True
            st.session_state.tab = st.session_state.kanaries
            st.session_state["kanaries"] = False
        
        avvio_misura = False
        # Se è stato premuto il tasto "Avvio Misura" nella pagina nuova misura
        if st.session_state.get("go_avvio_misura"):
            st.session_state["menu_key"] = "Predizione"
            avvio_misura = True
            st.session_state["go_avvio_misura"] = False
        
        visualizzazione = False
        if st.session_state.get("Visualizzazione"):
            st.session_state["menu_key"] = "Predizione"
            visualizzazione = True
            st.session_state["Visualizzazione"] = False

        fine = False 
        if st.session_state.get("fine_misura"): 
            st.session_state["menu_key"] = "Predizione"
            fine = True
            st.session_state["fine_misura"] = False

        # Elementi del menu
        menu_items = ["Home", "Predizione", "Storico", "Profilo Utente", "Info", "FAQ", "Logout"]

        menu_value = option_menu(
            "Menù",
            menu_items,
            icons=["house", "activity", "hourglass", "person", "info-circle", "question-circle", "box-arrow-right"],
            # per predizione volendo bar-chart, activity, graph-up
            # per storico clock, clock-history, hourglass
            menu_icon="list",
            default_index=menu_items.index(st.session_state["menu_key"]),
            styles={
                "container": {"padding": "0!important", "background-color": "#fafafa00"},
                "icon": {"font-size": "20px"}, 
                "menu-title": {"font-size": "20px", "font-family": "'Inter', sans-serif", "display": "flex",
                    "align-items": "center", "height": "40px"},
                "nav-link": {"font-size": "16px", "text-align": "left", "margin":"0px", "font-family": "'Inter', sans-serif"},
                "nav-link-selected": {"background-color": "#4da6ff", "font-family": "'Inter', sans-serif"}
            },
        )
        if calibrazione: 
            st.session_state.page = "Calibrazione"
            calibrazione = False
        elif avvio_misura:
            st.session_state.page = "AvvioMisura"
            avvio_misura = False
        elif visualizzazione:
            st.session_state.page = "Visualizzazione"
            visualizzazione = False
        elif fine: 
            st.session_state.page = "fine_misura"
            fine = False
        else:
            # Gestione della navigazione se l'utente ha selezionato una voce diversa
            selected_page = menu_value.lower().replace(" ", "_")
            if selected_page != st.session_state.page:
                st.session_state.page = selected_page
                st.session_state.menu_key = menu_value
                st.rerun()
        
# ------------- INIZIO ----------------
if st.session_state.page== "None":
    go_to("Login")

# ------------- PAGINA HOME ----------------
if st.session_state.page == "home":
    st.title(f"Benvenuto, {st.session_state['user']}!")
    st.markdown("---")
    st.title("Home 🏠")
    st.subheader("Cosa desideri fare oggi?")
    _, col1, col2, _ = st.columns([4, 2, 2, 4])
    with col1:
        if st.button("Esegui una nuova misura", use_container_width=True):
            st.session_state["go_misura"] = True
            st.rerun()
    with col2:
        if st.button("Consulta storico dati", use_container_width=True):
            st.session_state["go_storico"] = True
            st.rerun()

# ------------- PAGINA NUOVA MISURA---------
if st.session_state.page == "predizione":

    @st.dialog("Sei sicuro di voler tornare alla Home?")
    def modal():
        st.write("Perderai tutte le modifiche fatte finora.")
        _, col = st.columns([2,1])
        with col:
            if st.button("Torna alla Home"):
                if "dispositivo_ECG" in st.session_state:
                    del st.session_state.dispositivo_ECG
                if "dispositivo_PPG" in st.session_state:
                    del st.session_state.dispositivo_PPG
                st.session_state.sono_passato_da_calibrazione = False         #aggiornare tutte le variabili flag alzate durante la prima parte della misura
                st.session_state.sono_passato_da_AvvioMisura = False
                if "calibrazione_scelta" in st.session_state:
                    st.session_state.calibrazione_scelta = None
                if "Selezione_calibrazione" in st.session_state:
                    del st.session_state.selezione_calibrazione
                st.session_state["go_home"] = True
                st.rerun()

    st.subheader("Nuova misura")
    col_1, col_2, col_3 = st.columns([8,1,1])
    with col_2:
        if st.button("Indietro", use_container_width=True):
            #st.session_state.show_modal = True
            #st.rerun()
            modal()
    with col_3:
        if st.session_state.sono_passato_da_calibrazione==True:
            if st.button("Avanti", use_container_width=True):
                go_to("Calibrazione")
                st.session_state["go_calibrazione"] = True
                st.rerun()

    col1, col2 = st.columns([2, 2])
    with col1:
        if st.session_state.sono_passato_da_calibrazione == True:
            old_scelta = st.session_state.dispositivo_ECG
            index = next(i for i, d in enumerate(lista_dispositivi_ECG) if d["nome"] == old_scelta)
        else: 
            index = None
        
        st.markdown("### Seleziona sensore ECG")
        scelta = st.selectbox("Vai a:", [d["nome"] for d in lista_dispositivi_ECG], index=index)
        if scelta:
            st.session_state["dispositivo_ECG"] = scelta
    with col2: 
        st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Sensore ECG</b></p>", unsafe_allow_html=True)
        if "dispositivo_ECG" in st.session_state:
            if scelta:
                ecg_nome = st.session_state.dispositivo_ECG
                ecg_disp = next(d for d in lista_dispositivi_ECG if d["nome"] == ecg_nome)
                st.markdown(f"{st.session_state.dispositivo_ECG}")
                _, col_img, _ = st.columns([5.5,3,4])
                with col_img:
                    st.image(ecg_disp["img"], width=80)

    st.markdown("---")
    col1, col2 = st.columns([2, 2])
    with col1:
        if st.session_state.sono_passato_da_calibrazione == True:
            old_scelta1 = st.session_state.dispositivo_PPG
            index1 = next(i for i, d in enumerate(lista_dispositivi_PPG) if d["nome"] == old_scelta1)
        else: 
            index1 = None

        st.markdown("### Seleziona sensore Pletismografico")
        scelta1 = st.selectbox("Vai a:", [d["nome"] for d in lista_dispositivi_PPG], index=index1)
        if scelta1:
            st.session_state["dispositivo_PPG"] = scelta1
    with col2: 
        st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Sensore Pletismografico</b></p>", unsafe_allow_html=True)
        if "dispositivo_PPG" in st.session_state:
            if scelta1:
                ppg_nome = st.session_state.dispositivo_PPG
                ppg_disp = next(d for d in lista_dispositivi_PPG if d["nome"] == ppg_nome)
                st.markdown(f"{st.session_state.dispositivo_PPG}")
                _, col_img, _ = st.columns([5.5,3,4])
                with col_img:
                    st.image(ppg_disp["img"], width=80)

    st.markdown("---")
    if "dispositivo_ECG" in st.session_state and "dispositivo_PPG" in st.session_state:
        if scelta != "" and scelta1 != "":
            _, col = st.columns([8,1.5])
            with col: 
                if st.button("Procedi a calibrazione", use_container_width=True):
                    # if "calibrazione_scelta" in st.session_state:
                    #     del st.session_state.calibrazione_scelta
                    if "selezione_calibrazione" in st.session_state:
                        del st.session_state.selezione_calibrazione
                    st.session_state["go_calibrazione"] = True
                    st.rerun()

# ------------- PAGINA CALIBRAZIONE -----------
if st.session_state.page == "Calibrazione":
    st.session_state.sono_passato_da_calibrazione = True
    #st.session_state.go_calibrazione = True
    
    if "trovato" in st.session_state:
        st.session_state.trovato = None
    if "ECG" in st.session_state:
        del st.session_state["ECG"]

    st.subheader("Calibrazione")
    col_1, col_2, col_3 = st.columns([8,1,1])
    with col_2:
        if st.button("Indietro", on_click=lambda: st.session_state.__setitem__("go_calibrazione", False), use_container_width=True):
            st.session_state.__setitem__("go_calibrazione", False)
            st.session_state.page = "predizione"
            st.rerun()

    with col_3:
        if st.session_state.sono_passato_da_AvvioMisura == True:
            if st.button("Avanti", on_click=lambda: st.session_state.__setitem__("go_avvio_misura", True), use_container_width=True):
                st.session_state.go_calibrazione = False
                st.session_state.__setitem__("go_avvio_misura", True)
                st.rerun()

    col1, _, col2= st.columns([0.77, 0.1, 2])
    with col1: 
        st.markdown(f"<p style='font-size:16px; text-align:left;'>Vuoi usare una calibrazione già registrata?</p>", unsafe_allow_html=True)

        if "kanaries" not in st.session_state:
            if st.session_state.calibrazione_scelta != None:
                st.session_state.tab = "Calibrazione registrata"
            else:
                st.session_state.tab = None

        ui.tabs(options=['Calibrazione registrata', 'Nuova calibrazione'], default_value=st.session_state.tab, key="kanaries")
        
        tab = st.session_state.get("tab")

        if tab == "Calibrazione registrata":
            st.write("")
        elif tab == "Nuova calibrazione":
            st.write("")
        else:
            st.info("Seleziona una tab per continuare")

    with col2: 
        if tab == "Calibrazione registrata":
            st.session_state.count = 0
            st.markdown(f"<p style='font-size:16px; text-align:center;'><b>Calibrazione esistente</b></p>", unsafe_allow_html=True)

            if (
                st.session_state.calibrazione_scelta is not None
                and st.session_state.calibrazione_scelta in calibrazioni
            ):
                index_default = calibrazioni.index(st.session_state.calibrazione_scelta)
            else:
                index_default = None

            scelta = st.selectbox("Scegli la calibrazione:", calibrazioni, on_change=lambda: st.session_state.__setitem__("sel_calibrazione", True), 
                                  index=index_default, placeholder="Scegli un'opzione", key="scelta")

            if scelta:
                c1, _, c2 = st.columns([2,2.5,1])
                with c1:
                    st.markdown(f"<p style='font-size:16px; text-align:left;'>Vuoi scegliere: {scelta}?</p>", unsafe_allow_html=True)
                    #st.write(f"Vuoi scegliere: {scelta}?")
                with c2:
                    st.button("Conferma", on_click=lambda: Scelta_calibrazione(scelta), use_container_width=True)

            if "calibrazione_scelta" in st.session_state and st.session_state.calibrazione_scelta != None:
                st.markdown("---")
                st.subheader(f"Recap:")

                c1, c2, c3 = st.columns([1,1,1])
                with c1: 
                    st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Sensore ECG</b></p>", unsafe_allow_html=True)
                    ecg_nome = st.session_state.dispositivo_ECG
                    ecg_disp = next(d for d in lista_dispositivi_ECG if d["nome"] == ecg_nome)
                    st.markdown(f"{st.session_state.dispositivo_ECG}")
                    _, col_img, _ = st.columns([4,3,4])
                    with col_img:
                        st.image(ecg_disp["img"], width=80)

                with c2: 
                    st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Sensore PPG</b></p>", unsafe_allow_html=True)
                    ppg_nome = st.session_state.dispositivo_PPG
                    ppg_disp = next(d for d in lista_dispositivi_PPG if d["nome"] == ppg_nome)
                    st.markdown(f"{st.session_state.dispositivo_PPG}")
                    _, col_img, _ = st.columns([4,3,4])
                    with col_img:
                        st.image(ppg_disp["img"], width=80)

                with c3: 
                    st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Calibrazione selezionata</b></p>", unsafe_allow_html=True)
                    st.markdown(f"{st.session_state.calibrazione_scelta}")
                
                st.markdown("---")
                _, col = st.columns([4.5,1])
                with col:
                    if st.button("Accetta settings", on_click=lambda: st.session_state.__setitem__("go_avvio_misura", True), use_container_width=True):
                        st.session_state.go_calibrazione = False
                        st.session_state.calibrazione = scelta
                        st.session_state.__setitem__("go_avvio_misura", True)
                        st.rerun()

        elif tab == "Nuova calibrazione":
            st.session_state.count += 1
            st.subheader("Procedura nuova calibrazione...")
            st.write("Procedura nuova calibrazione")
            if st.session_state.count == 1:
                st.session_state.calibrazione_scelta = None
                st.session_state.sono_passato_da_AvvioMisura = False
                st.session_state.go_calibrazione = True
                st.rerun()

# ------------- PAGINA AVVIO MISURA ----------
st.markdown("""
<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
""", unsafe_allow_html=True)

def render_device(name, key):
    selected = st.session_state.get(key, False)
    color = "#4da6ff" if selected else "rgba(0,0,0,0.05)"
    border_color = "#4da6ff" if selected else "#5555557B"

    icon_name = "bluetooth_connected" if selected else "bluetooth_disabled"
    icon_html = f'<span class="material-icons" style="font-size:24px; margin-right:8px;">{icon_name}</span>'

    st.markdown(f"""
        <div style="
            display:flex;
            align-items:center;
            justify-content:center;
            padding:8px 16px;
            margin-top:0px;
            margin-bottom:15px;
            margin-left: auto;
            margin-right: auto;
            border-radius:12px;
            width: 200px;   /* larghezza fissa */
            height: 40px;   /* altezza fissa */
            background-color:{color};
            border: 1px solid {border_color};
            color:white;
            font-weight:normal;
            cursor:default;
            box-sizing:border-box;  /* include padding in width/height */
            gap:8px;   /* spazio tra icona e testo */
        ">
            {icon_html} {name}
        </div>
    """, unsafe_allow_html=True)

if st.session_state.page == "AvvioMisura":
    st.session_state.sono_passato_da_AvvioMisura=True
    st.subheader("Avvio Misura")

    col_1, col_2, col_3 = st.columns([8,1,1])
    with col_2:
        st.button("Indietro", key="indietro_misura", on_click=lambda: st.session_state.__setitem__("go_calibrazione", True), use_container_width=True)
        st.session_state["ricerca_avviata"] = False

    #with col_3:
        #st.button("Avanti", key="avanti_misura", disabled=not st.session_state.avanti_enabled, use_container_width=True)
        # if st.session_state.worker_process is None:
        #     process = subprocess.Popen(
        #         ["python", "programma_background.py"],
        #         stdout=subprocess.DEVNULL,
        #         stderr=subprocess.DEVNULL
        #     )
        #     st.session_state.worker_process = process
        #     st.success("Processo avviato")

        #if st.session_state.sono_passato_da_AvvioMisura==True:
            #st.button("Avanti", key="avanti_misura", on_click=lambda: go_to("AvvioMisura"), use_container_width=True)
            #st.session_state["sel_calibrazione"] = False
            #st.session_state["go_avvio_misura"] = True
    #st.markdown("Procedura di avvio misura...") 
    st.markdown("Collegamento con i dispositivi selezionati...")

    # Funzione di scansione BLE
    async def scan_ble():
        return await BleakScanner.discover(timeout=5)
    
    # Funzione di connessione BLE
    def connect_to_device_sync(address):
        async def do_connect():
            async with BleakClient(address) as client:
                await client.connect()
                return client.is_connected

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(do_connect())
        loop.close()
        return result

    # inizializza lo stato se non esiste
    for dev in ["ECG", "PPG"]:
        if dev not in st.session_state:
            st.session_state[dev] = False  # False = non selezionato

    _, c1, _  = st.columns([0.5,1,0.5])
    with c1: 
        st.markdown(f"<p style='font-size:18px; text-align:center;'><b>Ricerca dei sensori:</b></p>", unsafe_allow_html=True)
        #ecg_nome = st.session_state.dispositivo_ECG
        #ecg_nome = "iPhone di Giorgia"
        #ppg_nome = st.session_state.dispositivo_PPG
        ecg_nome = "boardECG"
        ppg_nome = "boardPPG"

        _, col, _ = st.columns([1,2,1])
        with col:
            render_device(st.session_state.dispositivo_ECG, key="ECG")
            render_device(st.session_state.dispositivo_PPG, key="PPG")

        _, col1, col2, _ = st.columns([0.2,1,1,0.2])
        with col1: 
            if st.button("Torna alla selezione dispostivi", on_click=lambda: st.session_state.__setitem__("page", "predizione"), use_container_width=True):
                st.session_state.ricerca_avviata = False
                st.session_state.trovato = None
                st.session_state.tentativo_connessione = False
                st.session_state.connected = None
                st.session_state.go_calibrazione = False
                st.rerun()
        with col2:
            target_devices = {"ECG": ecg_nome, "PPG": ppg_nome} 
            if st.button("Inizia la ricerca dei dispositivi", on_click=lambda: st.session_state.__setitem__("go_avvio_misura", True), use_container_width=True): 
                devices = asyncio.run(scan_ble())
                found = {}

                for d in devices:
                    if d.name == ecg_nome:
                        found["ECG"] = d.name
                    if d.name == ppg_nome:
                        found["PPG"] = d.name

                if "ECG" in found and "PPG" in found:
                    st.success("Sensori trovati")

                    st.session_state["ECG"] = True
                    st.session_state["PPG"] = True

                    st.session_state.avanti_enabled = True
                    st.session_state.device_names = found

                    st.session_state.go_avvio_misura = True
                    st.rerun()
                else:
                    st.error("Sensori non trovati")

                    st.session_state["ECG"] = False
                    st.session_state["PPG"] = False
                    st.session_state.go_avvio_misura = True
                    st.rerun()
        

    st.markdown("---")
    _, c = st.columns([8,1])
    with c:
        if st.session_state.avanti_enabled == True:
                #if st.button(f"Avanti", on_click=lambda: st.session_state.__setitem__("Visualizzazione", True), use_container_width=True):
                if st.button(f"Avanti", on_click=lambda: st.session_state.__setitem__("Visualizzazione", True), use_container_width=True):
                    if st.session_state.worker_process is None:
                        calibrazionen = st.session_state.calibrazione_da_tenere_fine_misura
                        process = subprocess.Popen(
                            ["python", "programma_background.py", str(calibrazionen)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        st.session_state.worker_process = process
                        st.success("Processo avviato")
                    
                    #st.session_state.predizione = False
                    st.session_state.go_calibrazione = False
                    st.session_state.page["Visualizzazione"] = True
                    st.rerun()

        if st.session_state.ricerca_avviata and st.session_state.trovato is None:
            st.info("Ricerca dei sensori ECG in corso...")
        elif st.session_state.ricerca_avviata and st.session_state.trovato is not None and st.session_state.tentativo_connessione is False:
            st.success(f"Sensore {ecg_nome} trovato!")
        elif st.session_state.ricerca_avviata and st.session_state.tentativo_connessione and st.session_state.connected is None:
            st.info("Tentativo di connessione...")

        if st.session_state.ricerca_avviata and st.session_state.trovato is None:
            st.error(f"Sensore {ecg_nome} non trovato. Assicurati che sia acceso e nelle vicinanze.")
        elif st.session_state.ricerca_avviata and st.session_state.trovato is not None and st.session_state.tentativo_connessione is False:
            st.success(f"Sensore {ecg_nome} trovato!")
        # elif st.session_state.ricerca_avviata and st.session_state.tentativo_connessione and st.session_state.connected is None:
        #     st.info("Tentativo di connessione...")
        elif st.session_state.ricerca_avviata and st.session_state.tentativo_connessione and st.session_state.connected is None:
            st.error("Connessione fallita.") 
        elif st.session_state.ricerca_avviata and st.session_state.tentativo_connessione and st.session_state.connected is not None:
            st.success(f"Sensore {ecg_nome} connesso correttamente!")
            
                    

# ------------- PAGINA LOGIN --------------------------
if st.session_state.page == "Login":
    st.title("Monitoraggio della Pressione Arteriosa 🩺")

    # Suddivisione della pagina in 3 colonne per centrare il modulo di login
    col1, col2, col3 = st.columns([2, 1.5, 2]) 

    with col2:
        # Flag di stato per mostrare/nascondere i moduli
        if "show_register" not in st.session_state:
            st.session_state.show_register = False
        if "show_login" not in st.session_state:
            st.session_state.show_login = False
        if "registration_success" not in st.session_state:
            st.session_state.registration_success = False

        st.subheader("Login 🔐")
        st.caption("Accedi con il tuo account o creane uno nuovo.")

        # Colonne: margine, bottone1, spazio, bottone2, margine
        _, b1, b2, _ = st.columns([1, 2, 2, 1])

        with b1:
            registrati = st.button("Registrati", key="reg", use_container_width=True)
        with b2:
            accedi = st.button("Accedi", key="acc", use_container_width=True)
        
        if registrati: 
            st.session_state.show_register = True
            st.session_state.show_login = False
            st.session_state.registration_success = False
        if accedi:
            st.session_state.show_login = True
            st.session_state.show_register = False
            st.session_state.registration_success = False

        if st.session_state.show_register:
            st.subheader("Registrazione 📝")
            nome = st.text_input("Nome")
            cognome = st.text_input("Cognome")
            data_nascita = st.date_input("Data di nascita", value=pd.to_datetime("2000-01-01").date(), min_value=pd.to_datetime("1900-01-01").date(), max_value=pd.to_datetime("today").date())
            sesso = st.selectbox("Sesso", ["M", "F"])
            peso = st.number_input("Peso (kg)", min_value=0.0, format="%.2f")
            altezza = st.number_input("Altezza (cm)", min_value=0.0, format="%.2f")
            col1, col2 = st.columns([1.5,3])
            with col1:
                prefisso = st.selectbox("Prefisso", ["+39", "+1", "+44"])
            with col2:
                numero = st.text_input("Numero di telefono", value="", max_chars=10)
            col3, col4 = st.columns([1.5,3])
            with col3:
                pref_emergenza = st.selectbox("Prefisso ice", ["+39", "+1", "+44"])
            with col4: 
                ice = st.text_input("Numero contatto di emergenza", value="", max_chars=10)
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            new_password_confirm = st.text_input("Conferma Password", type="password")
            if st.button("Crea account", use_container_width=True):
                if not nome or not cognome or not new_username or not new_password or not new_password_confirm or not numero or not ice or not data_nascita or not sesso or not peso or not altezza:
                    st.error("Tutti i campi sono obbligatori!")
                elif peso <= 0.0 or altezza <= 0.0:
                    st.error("Peso e altezza devono essere maggiori di zero.")
                elif data_nascita >= pd.to_datetime("today").date():
                    st.error("La data di nascita non può essere nel futuro.")
                elif not numero.isdigit() or not ice.isdigit():
                    st.error("I numeri di telefono devono contenere solo cifre!")
                elif len(new_password) < 6:
                    st.error("La password deve essere lunga almeno 6 caratteri.")
                elif new_password != new_password_confirm:
                    st.error("Le password non corrispondono.")
                elif register_user(new_username, new_password, nome, cognome, data_nascita, sesso, peso, altezza, f"{prefisso}{numero}", f"{pref_emergenza}{ice}"):
                    st.success("Registrazione completata! Ora puoi effettuare il login.")
                    st.session_state.show_register = False            # Torna alla schermata principale
                    st.session_state.registration_success = True
                    st.rerun()
                else:
                    get_informazioni_utenti(new_username, f"{prefisso}{numero}")
        
        elif st.session_state.show_login:
            st.subheader("Login 🔐")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.button("Login", use_container_width=True):
                if authenticate_user(username, password):
                    st.session_state.user = username
                    st.session_state.show_login = False
                    st.session_state.registration_success = False
                    go_to("home")
                    st.session_state.menu_open = True
                    st.rerun()
                else:
                    st.error("Credenziali errate.")

        # Messaggio di registrazione completata
        if st.session_state.registration_success:
            st.success("Registrazione completata!  \nOra puoi effettuare il login.")

# ------------- PAGINA PROFILO UTENTE --------------------------
# def profile_screen():
#     st.title("Profilo Utente 👤")

#     user = st.session_state["user"]
#     data = get_user_data(user)

#     if not data:
#         st.error("Impossibile trovare i tuoi dati nel database.")
#         return

#     nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice, pic = data

#     col1, col2 = st.columns([1, 3])
#     with col1:
#         st.subheader("Immagine Profilo:")

#         # Visualizzazione immagine statica di esempio
#         #st.image("https://www.w3schools.com/howto/img_avatar.png", width=150)
#         #st.image("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg", width=150)
        
#         # Mostro immagine attuale se presente, altrimenti immagine di default
#         if pic:
#             _, img, _ = st.columns([1, 4, 0.5])
#             with img:
#                 pic = Image.open(io.BytesIO(pic))
#                 pic = ImageOps.fit(pic, (150, 150))

#                 # Maschera circolare
#                 mask = Image.new('L', (150, 150), 0)
#                 draw = ImageDraw.Draw(mask)
#                 draw.ellipse((0, 0, 150, 150), fill=255)
#                 pic.putalpha(mask)
#                 st.image(pic, width=150)
#         else:
#             #st.image("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg", width=150)
#             _, img, _ = st.columns([0.5, 4, 1])
#             with img:
#                 st.markdown("""
#                 <div class="avatar-mask-wrapper">
#                     <div class="avatar-mask"></div>
#                 </div>
#                 """, unsafe_allow_html=True)
 
#         # Inizializzazione della chiave dinamica per resettare l'uploader
#         if "uploader_key" not in st.session_state:
#             st.session_state.uploader_key = 0

#         # Caricamento nuova immagine
#         new_pic = st.file_uploader("Carica nuova immagine", type=["png", "jpg", "jpeg"], key=f"file_uploader_pic_{st.session_state.uploader_key}")
#         if new_pic is not None:
#             # Converti l'immagine in base64 per memorizzarla nel database
#             pic_data = new_pic.read()
#             # Aggiorna l'immagine nel database
#             update_user_pic(user, pic_data)

#             st.success("Immagine caricata con successo!")
#             # Incrementare la chiave serve a ricreare l'uploader e resettarlo
#             st.session_state.uploader_key += 1
#             st.rerun()

#     with col2:
#         st.subheader("Dati personali")
#         st.text_input("Nome", value=nome, disabled=True)
#         st.text_input("Cognome", value=cognome, disabled=True)
#         st.text_input("Data di nascita", value=data_nascita, disabled=True)
#         st.text_input("Sesso", value=sesso, disabled=True)

#         if "edit_mode" not in st.session_state:
#             st.session_state.edit_mode = False
        
#         if not st.session_state.edit_mode:
#             st.number_input("Peso (kg)", value=peso, disabled=True)
#             st.number_input("Altezza (cm)", value=altezza, disabled=True)
#             if st.button("Modifica dati personali"):
#                 st.session_state.edit_mode = True
#         else:
#             new_peso = st.number_input("Peso (kg)", value=peso, key="peso_input")
#             new_altezza = st.number_input("Altezza (cm)", value=altezza, key="altezza_input")

#             col1, _, col2 = st.columns([1, 5, 1])
#             with col1:
#                 if st.button("Annulla"):
#                     st.session_state.edit_mode = False
#                     st.rerun()
#             with col2:
#                 if st.button("Salva dati"):
#                     if new_peso <= 0.0 or new_altezza <= 0.0:
#                         st.error("Peso e altezza devono essere maggiori di zero.")
#                     else:
#                         update_user_data(user, new_peso, new_altezza)
#                         st.success("Dati aggiornati con successo!")
#                         st.session_state.edit_mode = False
#                         st.rerun()

#         st.write("---")
#         st.subheader("Numeri di contatto 📞")

#         # Modalità di modifica
#         if "edit_contacts" not in st.session_state:
#             st.session_state.edit_contacts = False

#         if not st.session_state.edit_contacts:
#             st.text_input("Numero di telefono", value=telefono, disabled=True)
#             st.text_input("Contatto ICE", value=ice, disabled=True)
#             if st.button("Modifica dati"):
#                 st.session_state.edit_contacts = True
#         else:
#             new_tel = st.text_input("Numero di telefono", value=telefono)
#             new_ice = st.text_input("Contatto ICE", value=ice)

#             col1, _, col2 = st.columns([1, 5, 1])
#             with col1:
#                 if st.button("Annulla"):
#                     st.session_state.edit_contacts = False
#                     st.rerun()

#             with col2:
#                 if st.button("Salva numeri"):
#                     if not new_tel.isdigit() or not new_ice.isdigit():
#                         st.error("I numeri devono contenere solo cifre!")
#                     else:
#                         update_user_contacts(user, new_tel, new_ice)
#                         st.success("Numeri aggiornati con successo!")
#                         st.session_state.edit_contacts = False
#                         st.rerun()
#         st.write("---")

#         # --- Cambio Password ---
#         st.subheader("Cambia Password 🔐")

#         with st.expander("Mostra / Nascondi"):
#             old_pass = st.text_input("Password attuale", type="password")
#             new_pass = st.text_input("Nuova password", type="password")
#             new_pass2 = st.text_input("Conferma nuova password", type="password")

#             if st.button("Aggiorna password"):
#                 # Verifica password attuale
#                 if not authenticate_user(user, old_pass):
#                     st.error("La password attuale non è corretta.")
#                 elif new_pass != new_pass2:
#                     st.error("Le nuove password non coincidono.")
#                 elif len(new_pass) < 6:
#                     st.error("La password deve essere lunga almeno 6 caratteri.")
#                 else:
#                     update_password(user, new_pass)
#                     st.success("Password cambiata con successo!")

# if st.session_state.page == "profilo_utente":
#     profile_screen()
def profile_screen():
    st.title("Profilo Utente 👤")

    user = st.session_state["user"]
    data = get_user_data(user)

    if not data:
        st.error("Impossibile trovare i tuoi dati nel database.")
        return

    nome, cognome, data_nascita, sesso, peso, altezza, telefono, ice, pic = data

    col1, col2 = st.columns([1, 3])
    with col1:
        st.subheader("Immagine Profilo:")

        # Visualizzazione immagine statica di esempio
        #st.image("https://www.w3schools.com/howto/img_avatar.png", width=150)
        #st.image("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg", width=150)
        
        # Mostro immagine attuale se presente, altrimenti immagine di default
        if pic:
            _, img, _ = st.columns([1, 4, 0.5])
            with img:
                pic = Image.open(io.BytesIO(pic))
                pic = ImageOps.fit(pic, (150, 150))

                # Maschera circolare
                mask = Image.new('L', (150, 150), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 150, 150), fill=255)
                pic.putalpha(mask)
                st.image(pic, width=150)
        else:
            #st.image("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/icons/person-circle.svg", width=150)
            _, img, _ = st.columns([0.5, 4, 1])
            with img:
                st.markdown("""
                <div class="avatar-mask-wrapper">
                    <div class="avatar-mask"></div>
                </div>
                """, unsafe_allow_html=True)
 
        # Inizializzazione della chiave dinamica per resettare l'uploader
        if "uploader_key" not in st.session_state:
            st.session_state.uploader_key = 0

        # Caricamento nuova immagine
        new_pic = st.file_uploader("Carica nuova immagine", type=["png", "jpg", "jpeg"], key=f"file_uploader_pic_{st.session_state.uploader_key}")
        if new_pic is not None:
            # Converti l'immagine in base64 per memorizzarla nel database
            pic_data = new_pic.read()
            # Aggiorna l'immagine nel database
            update_user_pic(user, pic_data)

            st.success("Immagine caricata con successo!")
            # Incrementare la chiave serve a ricreare l'uploader e resettarlo
            st.session_state.uploader_key += 1
            st.rerun()

    with col2:
        st.subheader("Dati personali")
        st.text_input("Nome", value=nome, disabled=True)
        st.text_input("Cognome", value=cognome, disabled=True)
        st.text_input("Data di nascita", value=data_nascita, disabled=True)
        st.text_input("Sesso", value=sesso, disabled=True)

        if "edit_mode" not in st.session_state:
            st.session_state.edit_mode = False

        if "flag_dati_personali" not in st.session_state:
            st.session_state.flag_dati_personali = None
        
        if not st.session_state.edit_mode:
            st.number_input("Peso (kg)", value=peso, disabled=True)
            st.number_input("Altezza (cm)", value=altezza, disabled=True)
            if st.button("Modifica dati personali"):
                st.session_state.edit_mode = True
                st.rerun()
        else:
            new_peso = st.number_input("Peso (kg)", value=peso, key="peso_input")
            new_altezza = st.number_input("Altezza (cm)", value=altezza, key="altezza_input")

            col1, _, col2 = st.columns([1, 5, 1])
            with col1:
                if st.button("Annulla", key="annulla_dati_personali", use_container_width=True):
                    st.session_state.edit_mode = False
                    st.rerun()
            with col2:
                if st.button("Salva dati", use_container_width=True):
                    if new_peso <= 0.0 or new_altezza <= 0.0:
                        st.session_state.flag_dati_personali = False
                        #st.error("Peso e altezza devono essere maggiori di zero.")
                    else:
                        update_user_data(user, new_peso, new_altezza)
                        st.session_state.flag_dati_personali = True
                        #st.success("Dati aggiornati con successo!")
                        st.session_state.edit_mode = False
                        st.rerun()

        if st.session_state.flag_dati_personali == True: 
            st.success("Dati aggiornati con successo!")
            st.session_state.flag_dati_personali = None
            #st.rerun()
        elif st.session_state.flag_dati_personali == False: 
            st.error("Peso e altezza devono essere maggiori di zero.")
            st.session_state.flag_dati_personali = None

        st.write("---")
        st.subheader("Numeri di contatto 📞")

        # Modalità di modifica
        if "edit_contacts" not in st.session_state:
            st.session_state.edit_contacts = False
            
        if "flag" not in st.session_state:
            st.session_state.flag = None

        if not st.session_state.edit_contacts:
            st.text_input("Numero di telefono", value=telefono, disabled=True)
            st.text_input("Contatto ICE", value=ice, disabled=True)
            if st.button("Modifica dati"):
                st.session_state.edit_contacts = True
                st.rerun()
        else:
            new_tel = st.text_input("Numero di telefono", value=telefono, max_chars=13)
            new_ice = st.text_input("Contatto ICE", value=ice, max_chars=13)

            col1, _, col2 = st.columns([1, 5, 1])
            with col1:
                if st.button("Annulla", key="annulla_contatti", use_container_width=True):
                    st.session_state.edit_contacts = False
                    st.rerun()
            
            with col2:
                if st.button("Salva numeri", use_container_width=True):
                    if len(new_tel) > 13 or  len(new_ice) > 13:
                        st.session_state.flag = False
                    elif not new_tel.isdigit() or not new_ice.isdigit():
                        st.error("I numeri devono contenere solo cifre!")
                    else:
                        update_user_contacts(user, new_tel, new_ice)
                        st.session_state.flag = True
                        #st.success("Numeri aggiornati con successo!")
                        st.session_state.edit_contacts = False
                        st.rerun()
        if st.session_state.flag == True: 
            st.success("Numeri aggiornati con successo!")
            st.session_state.edit_contacts = False
            st.session_state.flag = None
            #st.rerun()
        elif st.session_state.flag == False: 
            st.error("I numeri devono contenere al massimo 10 cifre oltre al prefisso!")
            st.session_state.flag = None

        st.write("---")

        # --- Cambio Password ---
        st.subheader("Cambia Password 🔐")

        with st.expander("Mostra / Nascondi"):
            old_pass = st.text_input("Password attuale", type="password")
            new_pass = st.text_input("Nuova password", type="password")
            new_pass2 = st.text_input("Conferma nuova password", type="password")

            if st.button("Aggiorna password"):
                # Verifica password attuale
                if not authenticate_user(user, old_pass):
                    st.error("La password attuale non è corretta.")
                elif new_pass != new_pass2:
                    st.error("Le nuove password non coincidono.")
                elif len(new_pass) < 6:
                    st.error("La password deve essere lunga almeno 6 caratteri.")
                else:
                    update_password(user, new_pass)
                    st.success("Password cambiata con successo!")

if st.session_state.page == "profilo_utente":
    profile_screen()
                    
# ------------- PAGINA INFORMAZIONI --------------------------
if st.session_state.page == "info":
    st.title("Informazioni ℹ️")
    st.markdown("""
    <div style="text-align:center">

    <div style="margin-bottom: 30px;">
        Questa applicazione consente di monitorare la pressione arteriosa in modo semplice e immediato.
    </div>

                
    *Funzionalità principali:*
    <ul style="
        display: inline-block;
        text-align: left;
        margin: 0 auto 30px auto;
        padding-left: 80px;
    ">
        <li>Registrazione e login sicuri</li>
        <li>Visualizzazione e aggiornamento del profilo utente</li>
        <li>Modifica dei numeri di contatto</li>
        <li>Cambio password</li>
        <li>Misurazione della pressione arteriosa tramite dispositivi Bluetooth</li>
        <li>Visualizzazione in tempo reale dei dati raccolti</li>
        <li>Visualizzazione dello storico delle misure</li>
    </ul>
                
    *Sicurezza:*
    La tua privacy è la nostra priorità. Tutti i dati sono memorizzati in modo sicuro e le password sono criptate.

    *Assistenza:*
    Per assistenza, contatta il supporto tecnico.
    </div>
    """, unsafe_allow_html=True)

# ------------- PAGINA FAQ --------------------------
if st.session_state.page == "faq":
    st.title("Domande Frequenti ❓")
    st.markdown("""
    <div style="text-align:left">
                
    *D: Perché è importante monitorare la pressione arteriosa?*  
    R: Monitorare la pressione arteriosa è fondamentale per prevenire malattie cardiovascolari e mantenere uno stile di vita sano.
   
    *D: Cos'è l'ipertensione?*  
    R: L'ipertensione è una condizione in cui la pressione del sangue nelle arterie è costantemente elevata, aumentando il rischio di problemi cardiaci.

                
    *D: Quante persone soffrono di ipertensione?*  
    R: Secondo l'Organizzazione Mondiale della Sanità, circa 1.13 miliardi di persone nel mondo soffrono di ipertensione.

    *D: Cosa è importante fare per diminuire il rischio di ipertensione?*  
    R: Adottare uno stile di vita sano, come una dieta equilibrata, esercizio fisico regolare, riduzione del consumo di sale e gestione dello stress.

    *D: Dove posso trovare informazioni sull'ipertensione?*  
    R: Puoi visitare il sito dell'[Organizzazione Mondiale della Sanità](https://www.who.int/news-room/fact-sheets/detail/hypertension) per ulteriori informazioni.
    </div>
    """, unsafe_allow_html=True)

# ------------- PAGINA LOGOUT --------------------------
if st.session_state.page == "logout":
    st.title("Logout 🚪")
    st.subheader("Sei sicuro di voler effettuare il logout?")

    _, col1, col2, _ = st.columns([4, 2, 2, 4])
    with col1:
        if st.button("Annulla", use_container_width=True):
            st.session_state["go_home"] = True
            st.rerun()
    with col2:
        if st.button("Logout", use_container_width=True):
            st.session_state.page = "Login"
            st.session_state.menu_open = False
            st.rerun()


# ------------- PAGINA STORICO --------------------------
if "show_stats" not in st.session_state:
    st.session_state.show_stats = False

if st.session_state.page == "storico":
    st.title("Storico Misure 🕒")
    user = st.session_state["user"]
    
    misure = get_misure_user(user)
    
    if st.session_state.show_stats:
        col11, _,col12 = st.columns([2, 0.2,  1])
    else:
        col11, col12 = st.columns([9, 1])

    with col11:
        st.subheader("Visualizzazione misura singola")
        if not misure:
            st.info("Non hai ancora registrato nessuna misura, inizia subito")
            #if st.button(...):
            #   st.session_state.page = predizione
        else:
            # Creiamo la lista per lo selectbox: "id - data_ora"
            options = [f"{row[0]} -- {row[1]}" for row in misure]
            selected = st.selectbox("Seleziona una misura:", options)

            if selected:
                misura_id = int(selected.split(" -- ")[0])
                data_ora, periodo, calibrazione_associata, segnali = get_misura_by_id(misura_id)     
                #st.write(f"Data della misura: {data_ora}")
                periodo = periodo[0] if periodo else "N/A"
                st.write(f"Periodo giornata della misura: {periodo}")
                calibrazione_associata = calibrazione_associata[0] if calibrazione_associata else "N/A"
                st.write(f"Calibrazione associata: {calibrazione_associata}")
                #st.write(f"Calibrazione usata nella misura: {calibrazione_associata}")
                #segnali = [r[0] for r in segnali]          # pressione_campione
                #indici = [r[1] for r in segnali]
                #fig, ax = plt.subplots()
                #ax.plot(indici, segnali)
                #ax.set_title(f"Andamento pressione - Misura {misura_id}")
                #ax.set_xlabel("Indice campione")
                #ax.set_ylabel("Pressione (mmHg)")
                #st.pyplot(fig)


                checkbox_options_multiple = [
                    {"label": "ECG", "id": "m1", "default_checked":False},
                    {"label": "PPG", "id": "m2", "default_checked":False},
                    {"label": "Pressione", "id": "m3", "default_checked":False},
                    {"label": "Frequenza Cardiaca", "id": "m4", "default_checked":False}
                ]
                radio_value_1 = ui.checkbox(mode="multiple", options=checkbox_options_multiple, key="cb4")
                selected_ids = [k for k, v in (radio_value_1 or {}).items() if v]

                if "m1" in selected_ids:
                    df_ecg = df_da_segnali(segnali, "ECG")
                    if df_ecg.empty:
                        st.warning("Nessun dato ECG disponibile per questa misura.")
                    else:
                        fig = px.line(
                            df_ecg,
                            x="t_scaled",
                            y="amp",
                            title="Segnale ECG"
                        )

                        fig.update_xaxes(title="Tempo (s × 1000)")
                        st.plotly_chart(fig, use_container_width=True)

                    # fig = px.line(x=segnali["ECG"]["ts"], y=segnali["ECG"]["amp"], title="Segnale ECG")
                    # fig.update_layout(
                    #     xaxis=dict(
                    #         rangeslider=dict(visible=True),
                    #         type="date"
                    #     )
                    # )
                    # st.plotly_chart(fig, use_container_width=True)

                if "m2" in selected_ids:
                    df_ppg = df_da_segnali(segnali, "PPG")
                    if df_ppg.empty:
                        st.warning("Nessun dato PPG disponibile per questa misura.")
                    else:
                        fig = px.line(
                            df_ppg,
                            x="t_scaled",
                            y="amp",
                            title="Segnale PPG"
                        )

                        fig.update_xaxes(title="Tempo (s × 1000)")
                        st.plotly_chart(fig, use_container_width=True)

                if "m3" in selected_ids:
                    #fig = px.line(df_pressione, x=segnali["PRESSIONE"]["ts"], y=segnali["PRESSIONE"]["amp"], title="Segnale Pressorio")
                    #fig.update_layout(
                    #    xaxis=dict(
                    #        rangeslider=dict(visible=True),
                    #        type="date"
                    #    )
                    #)
                    #st.plotly_chart(fig, use_container_width=True)

                    df_press_media = df_da_segnali(segnali, "Pressione")
                    df_press_sist = df_da_segnali(segnali, "Pressione_sist")
                    df_press_diast = df_da_segnali(segnali, "Pressione_diast")

                    if not df_press_media.empty:
                        df_press_media["tipo"] = "media"
                    if not df_press_sist.empty:
                        df_press_sist["tipo"] = "sistolica"
                    if not df_press_diast.empty:
                        df_press_diast["tipo"] = "diastolica"

                    df_press = pd.concat([df_press_media, df_press_sist, df_press_diast])

                    if df_press.empty:
                        st.warning("Nessun dato di pressione disponibile per questa misura.")
                    else:
                        fig = px.line(
                            df_press,
                            x="t_scaled",
                            y="amp",
                            color="tipo",
                            title="Segnale Pressorio"
                        )

                        fig.update_xaxes(title="Tempo (s × 1000)")
                        st.plotly_chart(fig, use_container_width=True)

                if "m4" in selected_ids:
                    df_hr = df_da_segnali(segnali, "HR")
                    if df_hr.empty:
                        st.warning("Nessun dato di frequenza cardiaca disponibile per questa misura.")
                    else:
                        fig = px.line(
                            df_hr,
                            x="t_scaled",
                            y="amp",
                            title="Frequenza Cardiaca"
                        )

                        fig.update_xaxes(title="Tempo (s × 1000)")
                        st.plotly_chart(fig, use_container_width=True)

    with col12:
        toggle = st.checkbox("Visualizza statistiche", value=False, key="show_stats")
        if toggle:
            st.subheader("Statistiche")
            range_option = st.selectbox(
                "Intervallo temporale:",
                ["Ultima settimana", "Ultimo mese", "Ultimi 3 mesi", "Sempre"]
            )
            # calcolo data di inizio
            start_date = get_start_date(range_option).strftime("%Y-%m-%d %H:%M:%S")

            # recupero misure
            df = get_misure_in_range(user, start_date)

            #st.markdown("### Indici statistici")

            if df.empty:
                st.info("Nessuna misura registrata in questo intervallo.")
            else:
                # Numero sessioni
                st.write(f"**Numero sessioni registrate:** {len(df)}")
                st.write("---")

                # Media globale pressione
                df_fin_press = df["media_pressione"].dropna()
                media_press = df_fin_press.mean()
                st.write(f"**Pressione media:** {media_press:.1f} mmHg")

                # min/max pressione
                st.write(f"**Pressione minima:** {df_fin_press.min():.1f} mmHg")
                st.write(f"**Pressione massima:** {df_fin_press.max():.1f} mmHg")
                st.write("---")

                toggle1 = st.checkbox("Visualizza Sistolica- Diastolica", value=False, key="show_stats_sistolica_diastolica")

                if toggle1:
                    df_fin = df["media_pressione_sist"].dropna()
                    media_press_sist = df_fin.mean()
                    st.write(f"**Pressione media Sistolica:** {media_press_sist:.1f} mmHg")
                    st.write(f"**Pressione minima Sistolica:** {df_fin.min():.1f} mmHg")
                    st.write(f"**Pressione massima Sistolica:** {df_fin.max():.1f} mmHg")
                    df_fin_diast = df["media_pressione_diast"].dropna()
                    media_press_diast = df_fin_diast.mean()
                    st.write(f"**Pressione media Diastolica:** {media_press_diast:.1f} mmHg")
                    st.write(f"**Pressione minima Diastolica:** {df_fin_diast.min():.1f} mmHg")
                    st.write(f"**Pressione massima Diastolica:** {df_fin_diast.max():.1f} mmHg")
                    st.write("---")
                else:
                    st.write("---")

                # Media globale frequenze
                df_fin_freq = df["media_frequenze"].dropna()
                media_freq = df_fin_freq.mean()
                st.write(f"**Frequenza media:** {media_freq:.1f} Hz")

                # min/max frequenze
                st.write(f"**Frequenza minima:** {df_fin_freq.min():.1f} Hz")
                st.write(f"**Frequenza massima:** {df_fin_freq.max():.1f} Hz")
                st.write("---")

                # Periodi del giorno
                st.subheader("Statistiche per periodo del giorno")
                range_option1 = st.selectbox(
                    "Periodo del giorno:",
                    ["Mattina", "Pomeriggio", "Sera"], key="range_stats_periodo")
                
                gruppi = df.groupby("periodo_giornata")["media_pressione"]
                gruppi1 = df.groupby("periodo_giornata")["media_frequenze"]
                gruppi2 = df.groupby("periodo_giornata")["media_pressione_sist"]
                gruppi3 = df.groupby("periodo_giornata")["media_pressione_diast"]

                # Filtriamo il dataframe in base al periodo selezionato
                if range_option1 == "Mattina":
                    df_periodo = df[df["periodo_giornata"] == "Mattina"]
                elif range_option1 == "Pomeriggio":
                    df_periodo = df[df["periodo_giornata"] == "Pomeriggio"]
                elif range_option1 == "Sera":
                    df_periodo = df[df["periodo_giornata"] == "Sera"]

                # Colonne di interesse
                colonne = ["media_pressione", "media_pressione_sist", "media_pressione_diast", "media_frequenze"]

                # Creiamo un dizionario con statistiche
                stats = {}
                for col in colonne:
                    if not df_periodo.empty:
                        stats[col] = {
                            "media": df_periodo[col].mean(),
                            "min": df_periodo[col].min(),
                            "max": df_periodo[col].max()
                        }
                    else:
                        stats[col] = {
                            "media": None,
                            "min": None,
                            "max": None
                        }

                # Mostriamo su Streamlit
                if stats["media_pressione"]["media"] is not None:
                    st.write(f"**Pressione media**")
                    st.write(f"**Media**: {stats['media_pressione']['media']:.3f} mmHg")
                    st.write(f"**Min**: {stats['media_pressione']['min']:.3f} mmHg")
                    st.write(f"**Max**: {stats['media_pressione']['max']:.3f} mmHg")
                    st.write("---")
                else:
                    st.warning("**Nessun dato di pressione disponibile per questo periodo.**")
                    st.write("---")

                if stats["media_pressione"]["media"] is not None:
                    toggle2 = st.checkbox("Visualizza Sistolica - Diastolica", value=False)
                    if toggle2:
                        c1, c2 = st.columns([1,1])
                        with c1:
                            st.write(f"**Pressione sistolica**")
                            st.write(f"**Media**: {stats['media_pressione_sist']['media']:.3f} mmHg")
                            st.write(f"**Min**: {stats['media_pressione_sist']['min']:.3f} mmHg")
                            st.write(f"**Max**: {stats['media_pressione_sist']['max']:.3f} mmHg")
                        with c2:
                            st.write(f"**Pressione diastolica**")
                            st.write(f"**Media**: {stats['media_pressione_diast']['media']:.3f} mmHg")
                            st.write(f"**Min**: {stats['media_pressione_diast']['min']:.3f} mmHg")
                            st.write(f"**Max**: {stats['media_pressione_diast']['max']:.3f} mmHg")
                        st.write("---")
                    else:
                        st.write("---")

                    st.write(f"**Frequenza cardiaca**")
                    st.write(f"**Media**: {stats['media_frequenze']['media']:.3f} bpm")
                    st.write(f"**Min**: {stats['media_frequenze']['min']:.3f} bpm")
                    st.write(f"**Max**: {stats['media_frequenze']['max']:.3f} bpm")
                    st.write("---")


#------------------------ SVOLGIMENTO MISURA-----------------------
if st.session_state.page == "Visualizzazione": 
    if "buffer_resettato" not in st.session_state:
        reset_valori_misura()
        st.session_state.buffer_resettato = True

    print("Avvio processo background")
    if st.session_state.worker_process is None:
        calibrazionen = st.session_state.calibrazione_da_tenere_fine_misura
        process = subprocess.Popen(
            ["python", "programma_background.py", str(calibrazionen)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, 
            text = True
        )
        st.session_state.worker_process = process
        st.success("Processo avviato")

    st.session_state["Visualizzazione"] = True
    st_autorefresh(interval=1500)     #da provare con valori vari per capire i limiti

    # Leggi dati DB aggiornati
    conn = sqlite3.connect(os.path.join(BASE_DIR, "users.db"))
    df = pd.read_sql_query("SELECT * FROM valori_misura ORDER BY timestamp_ecg DESC LIMIT 500", conn)
    conn.close()

    cola, colb = st.columns([8,1.2])
    with cola:
        st.title("Misurando...")
    with colb:
        #st.button("Interrompi misura", on_click=lambda: go_to("fine_misura"))
        if st.button("Interrompi misura", on_click=lambda: st.session_state.__setitem__("fine_misura", True), use_container_width=True):
            proc = st.session_state.worker_process
            if proc is not None:
                proc.terminate()   # manda SIGTERM
                proc.wait(timeout=5)
                st.session_state.worker_process = None
                st.success("Processo fermato")
            st.session_state["Visualizzazione"] = False
            st.session_state["Calibrazione"] = False
            st.session_state["fine_misura"] = True
            st.session_state.pop("buffer_resettato", None)
        #banner con la libreria nuova di gio
        #arresto gli algoritmi cosi non aggiungo altri dati

    col1, _, col2 = st.columns([4,0.5,1.5])
    df1 = get_valori_misura()
    df_ecg = finestra_temporale(df1, "timestamp_ecg", secondi=10)
    df_ppg = finestra_temporale(df1, "timestamp_ppg", secondi=10)
    # Ho aggiunto queste righe
    df_ecg = df_ecg.sort_values("timestamp_ecg")   # ordino per timestamp
    df_ppg = df_ppg.sort_values("timestamp_ppg")   # ordino per timestamp
    
    df_indici, last_timestamp_old = get_indici_misura()
    #df3, last_timestamp_old = get_indici_pressione()
    df3 = finestra_temporale(df_indici, "timestamp_pressione", secondi=60)
    #df_hr = get_valori_hr()
    df_hr = finestra_temporale(df_indici, "timestamp_hr", secondi=60)
    with col1:
        scelta = st.selectbox(
            "Scegli il segnale da visualizzare:",
            [" ", "Segnale ECG", "Segnale PPG", "Pressione", "Frequenza cardiaca", "Tutti i segnali"]
        )

        if scelta == "Segnale ECG":
            st.subheader("ECG nel tempo")
            if df_ecg.empty:
                st.warning("Nessun dato ECG disponibile.")
            else:
                df_ecg = finestra_temporale(df1, "timestamp_ecg", secondi=10)
                
                WINDOW_S = 10

                # tempo relativo in secondi (come per ECG)
                df_ecg["tempo_s"] = (df_ecg["timestamp_ecg"] - df_ecg["timestamp_ecg"].min()).dt.total_seconds()

                t_max = df_ecg["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_ecg_window = df_ecg[(df_ecg["tempo_s"] >= t_min) & (df_ecg["tempo_s"] <= t_max)]

                fig = px.line(
                    df_ecg_window,
                    x="tempo_s",
                    y="ampiezza_ecg",
                    title="Segnale ECG"
                )

                fig.update_layout(
                    xaxis=dict(
                        title="Tempo (s)",
                        range=[t_min, t_max],        # centrato sull’ultima finestra
                        rangeslider=dict(visible=True),
                        fixedrange=False
                    ),
                    yaxis_title="Ampiezza ECG",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)

                #st.line_chart(df_ecg.set_index("timestamp_ecg")["ampiezza_ecg"])
                # fig = px.line(df_ecg, x="timestamp_ecg", y="ampiezza_ecg", title="ECG nel tempo")
                # fig.update_layout(xaxis_title="Tempo", yaxis_title="Ampiezza ECG", template="plotly_dark")
                # st.plotly_chart(fig, use_container_width=True)

        elif scelta == "Segnale PPG":
            st.subheader("PPG nel tempo")
            if df_ppg.empty:
                st.warning("Nessun dato PPG disponibile.")
            else:
                # Ho aggiunto questo:
                df_ppg = finestra_temporale(df1, "timestamp_ppg", secondi=10)

                #st.line_chart(df_ppg.set_index("timestamp_ppg")["ampiezza_ppg"])
                # fig = px.line(df_ppg, x="timestamp_ppg", y="ampiezza_ppg", title="PPG nel tempo")
                # fig.update_layout(xaxis_title="Tempo", yaxis_title="Ampiezza PPG", template="plotly_dark")
                # st.plotly_chart(fig, use_container_width=True)
                WINDOW_S = 10

                # tempo relativo in secondi (come per ECG)
                df_ppg["tempo_s"] = (df_ppg["timestamp_ppg"] - df_ppg["timestamp_ppg"].min()).dt.total_seconds()

                t_max = df_ppg["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_ppg_window = df_ppg[(df_ppg["tempo_s"] >= t_min) & (df_ppg["tempo_s"] <= t_max)]

                fig = px.line(
                    df_ppg_window,
                    x="tempo_s",
                    y="ampiezza_ppg",
                    title="Segnale PPG"
                )

                fig.update_layout(
                    xaxis=dict(
                        title="Tempo (s)",
                        range=[t_min, t_max],        # centrato sull’ultima finestra
                        rangeslider=dict(visible=True),
                        fixedrange=False
                    ),
                    yaxis_title="Ampiezza PPG",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)

        elif scelta == "Pressione":
            st.subheader("Pressione nel tempo")
            #if df3.empty:
            #    st.warning("Nessun dato di pressione disponibile.")
            #else:
                #st.line_chart(df3.set_index("timestamp_pressione")["pressione_calcolata"])
            #    fig = px.line(df3, x="timestamp_pressione", y="pressione_calcolata", title="Pressione nel tempo")
            #    fig.update_layout(xaxis_title="Tempo", yaxis_title="Pressione", template="plotly_dark")
            #    st.plotly_chart(fig, use_container_width=True)

            if df3.empty:
                st.warning("Nessun dato di pressione disponibile.")
            else:
                WINDOW_S = 10  # se vuoi ultimi 10 secondi, oppure più se i dati sono più sparsi
                df3["tempo_s"] = (df3["timestamp_pressione"] - df3["timestamp_pressione"].min()).dt.total_seconds()

                t_max = df3["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df3_window = df3[(df3["tempo_s"] >= t_min) & (df3["tempo_s"] <= t_max)]

                # Trasformiamo in formato long per Plotly Express
                df_long = df3_window.melt(
                    id_vars="tempo_s", 
                    value_vars=["pressione_calcolata_sist", "pressione_calcolata_diast", "pressione_calcolata_media"],
                    var_name="Tipo di pressione", 
                    value_name="Valore"
                )
                # Grafico lineare con più curve
                fig = px.line(
                    df_long,
                    x="tempo_s",
                    y="Valore",
                    color="Tipo di pressione",  # genera automaticamente la legenda
                    title="Pressione nel tempo"
                )
                # Layout grafico
                fig.update_layout(
                    xaxis_title="Tempo (s)",
                    yaxis_title="Pressione (mmHg)",
                    template="plotly_dark"
                )
                st.plotly_chart(fig, use_container_width=True)

        elif scelta == "Frequenza cardiaca":
            st.subheader("Frequenza cardiaca nel tempo")
            if df_hr.empty:
                st.warning("Nessun dato di frequenza cardiaca disponibile.")
            else:
                WINDOW_S = 30  # la HR cambia più lentamente

                df_hr["tempo_s"] = (
                    df_hr["timestamp_hr"] - df_hr["timestamp_hr"].min()
                ).dt.total_seconds()

                t_max = df_hr["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_hr_window = df_hr[
                    (df_hr["tempo_s"] >= t_min) & (df_hr["tempo_s"] <= t_max)
                ]

                fig = px.line(
                    df_hr_window,
                    x="tempo_s",
                    y="hr",
                    title="Frequenza cardiaca nel tempo"
                )

                fig.update_layout(
                    xaxis_title="Tempo (s)",
                    yaxis_title="Frequenza cardiaca (bpm)",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)

        elif scelta == "Tutti i segnali":
            st.subheader("ECG nel tempo")
            if df_ecg.empty:
                st.warning("Nessun dato ECG disponibile.")
            else:
                df_ecg = finestra_temporale(df1, "timestamp_ecg", secondi=10)
                
                WINDOW_S = 10

                # tempo relativo in secondi (come per ECG)
                df_ecg["tempo_s"] = (df_ecg["timestamp_ecg"] - df_ecg["timestamp_ecg"].min()).dt.total_seconds()

                t_max = df_ecg["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_ecg_window = df_ecg[(df_ecg["tempo_s"] >= t_min) & (df_ecg["tempo_s"] <= t_max)]

                fig = px.line(
                    df_ecg_window,
                    x="tempo_s",
                    y="ampiezza_ecg",
                    title="Segnale ECG"
                )

                fig.update_layout(
                    xaxis=dict(
                        title="Tempo (s)",
                        range=[t_min, t_max],        # centrato sull’ultima finestra
                        rangeslider=dict(visible=True),
                        fixedrange=False
                    ),
                    yaxis_title="Ampiezza ECG",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("PPG nel tempo")
            if df_ppg.empty:
                st.warning("Nessun dato PPG disponibile.")
            else:
                # Ho aggiunto questo:
                df_ppg = finestra_temporale(df1, "timestamp_ppg", secondi=10)

                #st.line_chart(df_ppg.set_index("timestamp_ppg")["ampiezza_ppg"])
                # fig = px.line(df_ppg, x="timestamp_ppg", y="ampiezza_ppg", title="PPG nel tempo")
                # fig.update_layout(xaxis_title="Tempo", yaxis_title="Ampiezza PPG", template="plotly_dark")
                # st.plotly_chart(fig, use_container_width=True)
                WINDOW_S = 10

                # tempo relativo in secondi (come per ECG)
                df_ppg["tempo_s"] = (df_ppg["timestamp_ppg"] - df_ppg["timestamp_ppg"].min()).dt.total_seconds()

                t_max = df_ppg["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_ppg_window = df_ppg[(df_ppg["tempo_s"] >= t_min) & (df_ppg["tempo_s"] <= t_max)]

                fig = px.line(
                    df_ppg_window,
                    x="tempo_s",
                    y="ampiezza_ppg",
                    title="Segnale PPG"
                )

                fig.update_layout(
                    xaxis=dict(
                        title="Tempo (s)",
                        range=[t_min, t_max],        # centrato sull’ultima finestra
                        rangeslider=dict(visible=True),
                        fixedrange=False
                    ),
                    yaxis_title="Ampiezza PPG",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)

            st.subheader("Pressione nel tempo")
            # if df3.empty:
            #     st.warning("Nessun dato di pressione disponibile.")
            # else:
            #     #st.line_chart(df3.set_index("timestamp_pressione")["pressione_calcolata"])
            #     fig = px.line(df3, x="timestamp_pressione", y="pressione_calcolata", title="Pressione nel tempo")
            #     fig.update_layout(xaxis_title="Tempo", yaxis_title="Pressione", template="plotly_dark")
            #     st.plotly_chart(fig, use_container_width=True)

            if df3.empty:
                st.warning("Nessun dato di pressione disponibile.")
            else:
                WINDOW_S = 10  # se vuoi ultimi 10 secondi, oppure più se i dati sono più sparsi
                df3["tempo_s"] = (df3["timestamp_pressione"] - df3["timestamp_pressione"].min()).dt.total_seconds()

                t_max = df3["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df3_window = df3[(df3["tempo_s"] >= t_min) & (df3["tempo_s"] <= t_max)]

                # Trasformiamo in formato long per Plotly Express
                df_long = df3_window.melt(
                    id_vars="tempo_s", 
                    value_vars=["pressione_calcolata_sist", "pressione_calcolata_diast", "pressione_calcolata_media"],
                    var_name="Tipo di pressione", 
                    value_name="Valore"
                )
                # Grafico lineare con più curve
                fig = px.line(
                    df_long,
                    x="tempo_s",
                    y="Valore",
                    color="Tipo di pressione",  # genera automaticamente la legenda
                    title="Pressione nel tempo"
                )
                # Layout grafico
                fig.update_layout(
                    xaxis_title="Tempo (s)",
                    yaxis_title="Pressione (mmHg)",
                    template="plotly_dark"
                )
                st.plotly_chart(fig, use_container_width=True)

            st.subheader("Frequenza cardiaca nel tempo")
            if df_hr.empty:
                st.warning("Nessun dato di frequenza cardiaca disponibile.")
            else:
                WINDOW_S = 30  # la HR cambia più lentamente

                df_hr["tempo_s"] = (
                    df_hr["timestamp_hr"] - df_hr["timestamp_hr"].min()
                ).dt.total_seconds()

                t_max = df_hr["tempo_s"].max()
                t_min = max(0, t_max - WINDOW_S)

                df_hr_window = df_hr[
                    (df_hr["tempo_s"] >= t_min) & (df_hr["tempo_s"] <= t_max)
                ]

                fig = px.line(
                    df_hr_window,
                    x="tempo_s",
                    y="hr",
                    title="Frequenza cardiaca nel tempo"
                )

                fig.update_layout(
                    xaxis_title="Tempo (s)",
                    yaxis_title="Frequenza cardiaca (bpm)",
                    template="plotly_dark"
                )

                st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.markdown('<p style="font-size:20px;"><b>Pressione attuale:</b></p>', unsafe_allow_html=True)
        if not df3.empty:
            df_filtrato = df3[df3["timestamp_pressione"] > last_timestamp_old]
            press_act = df_filtrato["pressione_calcolata_media"]
            Press_mean = press_act.mean()
            st.subheader(f"{Press_mean:.3f} mmHg")
            toggle1 = st.checkbox("Visualizza Sistolica- Diastolica (mmHg)", value=False)

            if toggle1:
                col111, col222 = st.columns([1,1])
                with col111:
                    st.write("Pressione Sistolica:")
                    df_filtrato = df3[df3["timestamp_pressione"] > last_timestamp_old]
                    press_act = df_filtrato["pressione_calcolata_sist"]
                    Press_mean = press_act.mean()
                    st.subheader(f"{Press_mean:.3f}")
                with col222:
                    st.write("Pressione Diastolica:")
                    df_filtrato = df3[df3["timestamp_pressione"] > last_timestamp_old]
                    press_act = df_filtrato["pressione_calcolata_diast"]
                    Press_mean = press_act.mean()
                    st.subheader(f"{Press_mean:.3f}")
        else:
            st.write("Attendi, misura in avvio...")
        st.write("---")
        st.markdown('<p style="font-size:20px;"><b>Frequenza cardiaca attuale:</b></p>', unsafe_allow_html=True)
        if not df_hr.empty:
            df_filtrato1 = df_hr[df_hr["timestamp_hr"] > last_timestamp_old]
            hr_act = df_filtrato1["hr"]
            hr_mean = hr_act.mean()
            st.subheader(f"{hr_mean:.3f} bpm")
        else:
            st.write("Attendi, misura in avvio...")


#------------------------ FINE MISURA-----------------------
if "calendar_calue" not in st.session_state:
    st.session_state["calendar_calue"] = None
if "lista" not in st.session_state:
    st.session_state["lista"] = None

if st.session_state.page == "fine_misura":
    st.session_state["fine_misura"] = True

    calibrazionen = st.session_state.calibrazione_da_tenere_fine_misura

    cola, colb = st.columns([8,1.5])
    with cola:
        st.title("Ecco la tua misura")
    with colb:
        btn1,_, btn2 = st.columns([1,0.05,1])
        with btn1:
            salva = ui.button(
                "Salva",
                disabled=not (st.session_state.scelta != "" and st.session_state.calendar_calue is not None),
                # on_click=lambda: salva_misura(calendar_calue, scelta, lista) if (scelta != "" and calendar_calue is not None) else None
                key="salva_btn", 
                use_container_width=True
                )
        with btn2:
            scarta = ui.button("Scarta", key="scarta_btn")
                
        if salva: 
            salva_misura(st.session_state.calendar_calue, st.session_state.scelta, st.session_state.lista, st.session_state.user, st.session_state.calibrazione_da_tenere_fine_misura)
            st.session_state["fine_misura"] = False
            st.session_state["Calibrazione"] = False
            st.session_state["nuova_misura"] = False
            st.session_state["Predizione"] = False
            st.session_state["predizione"] = False
            st.session_state["go_home"] = True
            st.rerun()

        if scarta:
            st.session_state["fine_misura"] = False
            st.session_state["Calibrazione"] = False
            st.session_state["nuova_misura"] = False
            st.session_state["Predizione"] = False
            st.session_state["page"] = "home" 
            st.session_state["predizione"] = False
            st.session_state["go_home"] = True
            st.rerun()


        #if scelta != "" and calendar_calue!= None:
        #    ui.button("Salva", on_click=lambda: go_to("storico"))
        #else:
        #    ui.button("Salva", disabled=not (scelta != "" and calendar_calue!= None))

    col1, col2, col3 = st.columns([1,4,2])
    df1 = get_valori_misura()
    df2 = get_tutti_indici_misura()
    df_ecg = df1[["timestamp_ecg", "ampiezza_ecg"]]
    df_ppg = df1[["timestamp_ppg", "ampiezza_ppg"]]
    df_pressione = df2[["timestamp_pressione", "pressione_calcolata_media"]]
    df_pressione_sist = df2[["timestamp_pressione", "pressione_calcolata_sist"]]
    df_pressione_diast = df2[["timestamp_pressione", "pressione_calcolata_diast"]]
    df_hr = df2[["timestamp_hr", "hr"]]
    st.session_state.lista = crea_campioni_list(df_ecg, df_ppg, df_pressione, df_hr, df_pressione_sist, df_pressione_diast)

    df_ecg['timestamp_ecg'] = pd.to_datetime(df_ecg['timestamp_ecg'])
    df_ppg['timestamp_ppg'] = pd.to_datetime(df_ppg['timestamp_ppg'])
    df_pressione['timestamp_pressione'] = pd.to_datetime(df_pressione['timestamp_pressione'])
    df_hr['timestamp_hr'] = pd.to_datetime(df_hr['timestamp_hr'])
    
    with col1:
        checkbox_options_multiple = [
            {"label": "ECG", "id": "m1", "default_checked":False},
            {"label": "PPG", "id": "m2", "default_checked":False},
            {"label": "Pressione", "id": "m3", "default_checked":False},
            {"label": "frequenza cardiaca", "id": "m4", "default_checked":False}
        ]
        radio_value_1 = ui.checkbox(mode="multiple", options=checkbox_options_multiple, key="cb4")
        #or []
        selected_ids = [k for k, v in (radio_value_1 or {}).items() if v]
        #st.write("Selected Option:", radio_value_1)

    with col2:
        if "m1" in selected_ids:
            df_ecg["t_scaled"] = scala_tempo(df_ecg, "timestamp_ecg")

            fig = px.line(
                df_ecg,
                x="t_scaled",
                y="ampiezza_ecg",
                title="Segnale ECG"
            )
            fig.update_xaxes(title="Tempo (s × 1000)")
            st.plotly_chart(fig, use_container_width=True)

            # fig = px.line(df_ecg, x="timestamp_ecg", y="ampiezza_ecg", title="Segnale ECG")
            # fig.update_layout(
            #     xaxis=dict(
            #         rangeslider=dict(visible=True),
            #         type="date"
            #     )
            # )
            # st.plotly_chart(fig, use_container_width=True)

        if "m2" in selected_ids:
            df_ppg["t_scaled"] = scala_tempo(df_ppg, "timestamp_ppg")

            fig = px.line(
                df_ppg,
                x="t_scaled",
                y="ampiezza_ppg",
                title="Segnale PPG"
            )
            fig.update_xaxes(title="Tempo (s × 1000)")
            st.plotly_chart(fig, use_container_width=True)

        if "m3" in selected_ids:
            # fig = px.line(df_pressione, x="tempo", y="Pressione", title="Segnale Pressorio")
            # fig.update_layout(
            #     xaxis=dict(
            #         rangeslider=dict(visible=True),
            #         type="date"
            #     )
            # )
            # st.plotly_chart(fig, use_container_width=True)
            if (
                df_pressione.empty
                or df_pressione_sist.empty
                or df_pressione_diast.empty
            ):
                st.warning("Dati pressori incompleti: impossibile costruire il grafico.")
            else:
                df_pressione_finale = (
                    df_pressione.rename(columns={
                        "timestamp_pressione": "ts",
                        "pressione_calcolata_media": "media"
                    })
                    .merge(
                        df_pressione_sist.rename(columns={
                            "timestamp_pressione": "ts",
                            "pressione_calcolata_sist": "sistolica"
                        }),
                        on="ts",
                        how="inner"
                    )
                    .merge(
                        df_pressione_diast.rename(columns={
                            "timestamp_pressione": "ts",
                            "pressione_calcolata_diast": "diastolica"
                        }),
                        on="ts",
                        how="inner"
                    )
                )
    
                # trasforma in formato long
                df_long = df_pressione_finale.melt(id_vars="ts", 
                                            value_vars=["sistolica", "diastolica", "media"],
                                            var_name="tipo", 
                                            value_name="valore")
                # crea il grafico
                # fig = px.line(df_long, x="ts", y="valore", color="tipo", title="Segnale Pressorio")
                # fig.update_layout(
                #     xaxis=dict(
                #         rangeslider=dict(visible=True),
                #         type="date"
                #     )
                # )
                # st.plotly_chart(fig, use_container_width=True)

                df_long["t_scaled"] = scala_tempo(df_long, "ts")

                fig = px.line(
                    df_long,
                    x="t_scaled",
                    y="valore",
                    color="tipo",
                    title="Segnale Pressorio"
                )
                fig.update_xaxes(title="Tempo (s × 1000)")
                st.plotly_chart(fig, use_container_width=True)

        if "m4" in selected_ids:
            df_hr["t_scaled"] = scala_tempo(df_hr, "timestamp_hr")

            fig = px.line(
                df_hr,
                x="t_scaled",
                y="hr",
                title="Frequenza Cardiaca"
            )
            fig.update_xaxes(title="Tempo (s × 1000)")
            st.plotly_chart(fig, use_container_width=True)

    with col3:
        st.write("Seleziona informazioni misura")
        st.write("---")
        st.write("Che giorno è oggi?")
        ui.calendar(class_name=None, key="calendar_calue")
        #st.write("Calendar value is:", calendar_calue)
        #da controllare cosa sto scrivendo a schermo
        #st.write(ui.calendar)
        st.write("---")
        st.write("In che periodo della giornata stai svolgendo questa misura?")
        periodi = ["Mattina", "Pomeriggio", "Sera"]
        st.session_state.scelta = st.selectbox("Periodo giornata:", periodi, placeholder="Scegli un'opzione", index=None)
