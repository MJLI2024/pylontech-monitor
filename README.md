# Pylontech US5000 Dual UART Monitor

Sistema de monitorización en tiempo real para un banco de baterías **Pylontech US5000** conectadas en paralelo (configuración Master / Esclavo), desarrollado con **FastAPI**, **Tailwind CSS** y comunicación serie mediante UART.

---

## 🚀 Características Principales

* **Telemetría en Vivo Dual:** Lectura concurrente y sincronizada del puerto serie para extraer métricas detalladas tanto del módulo *Master* como del *Slave*.
* **Cálculo de Potencia Combinada:** Derivación precisa del voltaje total de la bancada y suma individual de potencias ($V \times I$) para mayor precisión a bajas corrientes.
* **Interfaz Web Moderna (Tailwind CSS):** 
  * Panel principal con círculo de Estado de Carga (SOC).
  * Tarjetas de salud, ciclos de carga e imbalance de celdas.
  * Temperaturas de batería, MOSFET y celdas extremas.
  * **Desglose independiente por módulo** (Master y Slave) con sus respectivas tensiones, corrientes, potencias y SOCs individuales.
  * Visor detallado de celdas (voltajes individuales por módulo).
* **Gestión de Eventos y Exportación:** Visualización del historial de alertas y eventos del sistema, con opción de descarga de datos en formato JSON.
* **Despliegue Contenedorizado:** Preparado para correr en Docker bajo entornos autohospedados (Zorin OS / Portainer).

---

## 🛠️ Stack Tecnológico

* **Backend:** Python 3.11, FastAPI, Uvicorn, PySerial.
* **Frontend:** HTML5, Tailwind CSS (vía CDN), JavaScript (Vanilla).
* **Contenedorización:** Docker, Docker Compose, Portainer.

---

## 📁 Estructura del Proyecto

```text
pylontech-monitor/
├── main.py              # API backend en FastAPI y gestor de puertos serie
├── index.html           # Interfaz gráfica principal del dashboard
├── logs.html            # Vista del historial de eventos
├── Dockerfile           # Definición de la imagen de Docker
├── docker-compose.yml   # Configuración para despliegue en Portainer / Docker
└── requirements.txt     # Dependencias de Python
