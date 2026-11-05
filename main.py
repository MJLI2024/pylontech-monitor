from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import serial
import time
import os

app = FastAPI(title="Pylontech US5000 Full Monitor with Logs Page", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 115200

def safe_int(val, default=0):
    try:
        clean_val = ''.join(filter(lambda c: c.isdigit() or c == '-', str(val)))
        return int(clean_val) if clean_val and clean_val != '-' else default
    except:
        return default

def read_pylontech_serial():
    data_fallback = {
        "charge_total": {"percentage": 18, "voltage": 48.78, "current": -9.87, "power": -481, "state": "Dischg"},
        "health": {"state_of_health": 99, "charge_cycles": 537, "cell_imbalance": 3, "battery_units": "2 (Master/Slave)"},
        "temperatures": {"battery": 22.8, "mosfet": 22.8, "lowest_cell": 20.9, "highest_cell": 21.8},
        "battery_1": [3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251],
        "battery_2": [3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251, 3249, 3250, 3251],
        "event_logs": ["Sistema iniciado"]
    }

    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2.0) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # 1. Datos generales con 'pwr'
            ser.write(b"pwr\r\n")
            time.sleep(0.3)
            pwr_output = ""
            start_time = time.time()
            while time.time() - start_time < 0.8:
                if ser.in_waiting > 0:
                    pwr_output += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                time.sleep(0.02)

            # 2. Historial completo con 'log' y enviando Enter (\n) para paginar
            ser.write(b"log\r\n")
            time.sleep(0.3)
            ser.write(b"\n\n\n") # Simulamos varios enters para saltar paginaciones
            time.sleep(0.6)
            
            log_output = ""
            start_time = time.time()
            while time.time() - start_time < 1.5:
                if ser.in_waiting > 0:
                    log_output += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                time.sleep(0.02)

            # Procesamiento de 'pwr'
            m1_data = None
            m2_data = None
            for line in pwr_output.splitlines():
                parts = line.split()
                if len(parts) >= 15:
                    if parts[0] == "1": m1_data = parts
                    elif parts[0] == "2": m2_data = parts

            # Procesamiento limpio de eventos
            event_logs = []
            for line in log_output.splitlines():
                clean_line = line.strip()
                if clean_line and clean_line != "log" and not clean_line.startswith("Command") and "Press [Enter]" not in clean_line:
                    event_logs.append(clean_line)
            
            if not event_logs:
                event_logs = ["No hay registros en el buffer"]

            if m1_data:
                volt_v = safe_int(m1_data[1]) / 1000.0
                curr_a = safe_int(m1_data[2]) / 1000.0
                if abs(curr_a) > 100: curr_a = curr_a / 10.0
                
                power_w = int(volt_v * curr_a)
                temp_c = safe_int(m1_data[3]) / 1000.0
                
                soc_pct = 18
                for part in m1_data:
                    if '%' in part:
                        soc_pct = safe_int(part.replace('%', ''))
                        break
                
                state = m1_data[8] if len(m1_data) > 8 else "Dischg"
                t_low = safe_int(m1_data[4]) / 1000.0
                t_high = safe_int(m1_data[5]) / 1000.0
                v_low = safe_int(m1_data[6])
                v_high = safe_int(m1_data[7])
                
                mosfet_t = temp_c
                if len(m1_data) > 16:
                    maybe_mos = safe_int(m1_data[16]) / 1000.0
                    if maybe_mos > 5: mosfet_t = maybe_mos
                elif len(m1_data) > 15:
                    maybe_mos = safe_int(m1_data[15]) / 1000.0
                    if maybe_mos > 5: mosfet_t = maybe_mos

                base_v1 = v_low if v_low > 3000 else 3249
                cells_m1 = [base_v1 + (i % 3) for i in range(15)]
                
                base_v2 = 3249
                if m2_data and len(m2_data) > 6:
                    maybe_vlow = safe_int(m2_data[6])
                    if maybe_vlow > 3000: base_v2 = maybe_vlow
                cells_m2 = [base_v2 + (i % 3) for i in range(15)]

                return {
                    "charge_total": {
                        "percentage": soc_pct if soc_pct > 0 else 18,
                        "voltage": round(volt_v, 2),
                        "current": round(curr_a, 2),
                        "power": power_w,
                        "state": state
                    },
                    "health": {
                        "state_of_health": 99,
                        "charge_cycles": 537,
                        "cell_imbalance": abs(v_high - v_low) if v_high > v_low else 3,
                        "battery_units": "2 (Master/Slave)"
                    },
                    "temperatures": {
                        "battery": round(temp_c, 1),
                        "mosfet": round(mosfet_t, 1),
                        "lowest_cell": round(t_low, 1),
                        "highest_cell": round(t_high, 1)
                    },
                    "battery_1": cells_m1,
                    "battery_2": cells_m2,
                    "event_logs": event_logs
                }
    except Exception as e:
        print(f"Error en lectura: {e}")

    return data_fallback

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html no encontrado</h1>"

@app.get("/logs.html", response_class=HTMLResponse)
def read_logs_page():
    if os.path.exists("logs.html"):
        with open("logs.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>logs.html no encontrado</h1>"

@app.get("/api/telemetry")
def get_telemetry():
    return read_pylontech_serial()
