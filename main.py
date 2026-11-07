"""
Monitor Pylontech US5000 vía consola serie (RS232/USB) con FastAPI.
Versión con desglose individual de corriente y potencia por módulo.
"""

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import serial
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

SERIAL_PORT = os.getenv("PYLON_PORT", "/dev/ttyUSB0")
BAUD_RATE = int(os.getenv("PYLON_BAUD", "115200"))
CACHE_TTL = float(os.getenv("PYLON_CACHE_TTL", "2.0"))
CMD_TIMEOUT = float(os.getenv("PYLON_CMD_TIMEOUT", "4.0"))
MAX_LOG_LINES = int(os.getenv("PYLON_MAX_LOG_LINES", "50"))
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pylontech")

PAGER_MARKER = "Press [Enter] to be continued"
PROMPT_RE = re.compile(r"[\w.]+>\s*$")

app = FastAPI(title="Pylontech US5000 Monitor", version="3.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_serial_lock = threading.Lock()
_cache: dict = {"data": None, "ts": 0.0}

def to_int(val, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(str(val).strip().rstrip("%"))
    except (ValueError, TypeError):
        return default

def send_command(ser: serial.Serial, cmd: str, timeout: float = CMD_TIMEOUT) -> str:
    ser.reset_input_buffer()
    ser.write(f"{cmd}\r\n".encode("ascii"))
    buf = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk.decode("ascii", errors="ignore")
        if PAGER_MARKER in buf:
            buf = buf.replace(PAGER_MARKER, "")
            ser.write(b"\r\n")
            continue
        if PROMPT_RE.search(buf):
            return buf
    return buf

def parse_pwr(text: str) -> list[dict]:
    header = None
    modules = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "Power" and "Volt" in parts:
            header = parts
            continue
        if header is None or not parts[0].isdigit():
            continue
        if "Absent" in parts:
            continue

        idx = {name: i for i, name in enumerate(header)}
        time_idx = idx.get("Time")

        def col(name, parts=parts, idx=idx, time_idx=time_idx):
            if name not in idx:
                return None
            i = idx[name] + (1 if time_idx is not None and idx[name] > time_idx else 0)
            return parts[i] if i < len(parts) else None

        try:
            mod = {
                "id": int(parts[0]),
                "volt_v": to_int(col("Volt")) / 1000.0,
                "curr_a": to_int(col("Curr")) / 1000.0,
                "temp_c": to_int(col("Tempr")) / 1000.0,
                "tlow_c": to_int(col("Tlow")) / 1000.0,
                "thigh_c": to_int(col("Thigh")) / 1000.0,
                "vlow_mv": to_int(col("Vlow")),
                "vhigh_mv": to_int(col("Vhigh")),
                "state": col("Base.St") or "Unknown",
                "soc": to_int(col("Coulomb")),
            }
        except TypeError:
            continue

        mos = to_int(col("MosTempr"))
        mod["mosfet_c"] = mos / 1000.0 if mos is not None else None
        modules.append(mod)
    return modules

def parse_bat(text: str) -> list[int]:
    cells = []
    in_table = False
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "Battery" and "Volt" in parts:
            in_table = True
            continue
        if in_table and parts[0].isdigit() and len(parts) > 1:
            mv = to_int(parts[1])
            if mv is not None:
                cells.append(mv)
    return cells

def parse_cycles(text: str) -> Optional[int]:
    m = re.search(r"CYCLE\s*Times\s*:?\s*(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None

def parse_log(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "log" or line.startswith("Command") or line.startswith("$$") or PROMPT_RE.fullmatch(line):
            continue
        lines.append(line)
    return lines[-MAX_LOG_LINES:]

def read_pylontech_serial() -> dict:
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.2) as ser:
        ser.write(b"\r\n")
        time.sleep(0.2)
        modules = parse_pwr(send_command(ser, "pwr"))
        if not modules:
            raise RuntimeError("`pwr` no devolvió ningún módulo presente")

        cells: dict[int, list[int]] = {}
        cycles: list[int] = []
        for mod in modules:
            cells[mod["id"]] = parse_bat(send_command(ser, f"bat {mod['id']}"))
            c = parse_cycles(send_command(ser, f"stat {mod['id']}"))
            if c is not None:
                cycles.append(c)

        events = parse_log(send_command(ser, "log", timeout=8.0))

    master_mod = next((m for m in modules if m["id"] == 1), modules[0])
    voltage = master_mod["volt_v"]

    # Suma inteligente de potencias individuales para mayor precisión
    total_power = sum(round(m["volt_v"] * m["curr_a"]) for m in modules)
    total_current = round(total_power / voltage, 2) if voltage > 0 else sum(m["curr_a"] for m in modules)

    soc = round(sum(m["soc"] for m in modules if m["soc"] is not None) / len(modules))
    imbalance = max(m["vhigh_mv"] for m in modules) - min(m["vlow_mv"] for m in modules)
    mosfets = [m["mosfet_c"] for m in modules if m["mosfet_c"] is not None]

    modules_detail = []
    for m in modules:
        modules_detail.append({
            "id": m["id"],
            "role": "Master" if m["id"] == 1 else "Slave",
            "voltage": m["volt_v"],
            "current": m["curr_a"],
            "power": round(m["volt_v"] * m["curr_a"]),
            "soc": m["soc"],
            "state": m["state"],
            "temp": m["temp_c"]
        })

    return {
        "charge_total": {
            "percentage": soc,
            "voltage": round(voltage, 2),
            "current": round(total_current, 2),
            "power": total_power,
            "state": master_mod["state"],
        },
        "modules_detail": modules_detail,
        "health": {
            "state_of_health": None,
            "charge_cycles": max(cycles) if cycles else None,
            "cell_imbalance": imbalance,
            "battery_units": len(modules),
        },
        "temperatures": {
            "battery": round(sum(m["temp_c"] for m in modules) / len(modules), 1),
            "mosfet": round(max(mosfets), 1) if mosfets else None,
            "lowest_cell": round(min(m["tlow_c"] for m in modules), 1),
            "highest_cell": round(max(m["thigh_c"] for m in modules), 1),
        },
        "battery_1": cells.get(1, []),
        "battery_2": cells.get(2, []),
        "event_logs": events or ["No hay registros en el buffer"],
    }

def _serve_html(name: str):
    path = BASE_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} no encontrado")
    return FileResponse(path, media_type="text/html")

@app.get("/")
@app.get("/index.html")
def read_root():
    return _serve_html("index.html")

@app.get("/logs.html")
def read_logs_page():
    return _serve_html("logs.html")

@app.get("/api/telemetry")
def get_telemetry():
    with _serial_lock:
        now = time.time()
        if _cache["data"] and now - _cache["ts"] < CACHE_TTL:
            return {**_cache["data"], "source": "live", "age_s": round(now - _cache["ts"], 1)}
        try:
            data = read_pylontech_serial()
            _cache.update(data=data, ts=now)
            return {**data, "source": "live", "age_s": 0.0}
        except (serial.SerialException, OSError, RuntimeError) as e:
            log.error("Error leyendo puerto: %s", e)
        if _cache["data"]:
            return {**_cache["data"], "source": "cache", "age_s": round(now - _cache["ts"], 1)}
    raise HTTPException(status_code=503, detail="Sin comunicación con la batería")
