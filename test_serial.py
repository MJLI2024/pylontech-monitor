import serial
import time

PORT = "/dev/ttyUSB0"
BAUD = 115200

print(f"Abriendo puerto serie {PORT} a {BAUD} baudios...")

try:
    with serial.Serial(PORT, BAUD, timeout=2) as ser:
        print("Puerto abierto con éxito. Enviando comando de activación/estado...")
        
        # Limpiamos búferes
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Muchas baterías Pylontech responden al comando 'pwr', 'bat' o simplemente a un par de intros
        ser.write(b"\r\n")
        time.sleep(0.5)
        ser.write(b"pwr\r\n")
        time.sleep(1.0)

        # Leemos todo lo que hay disponible en la consola
        if ser.in_waiting > 0:
            output = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
            print("\n--- RESPUESTA DE LA BATERÍA ---")
            print(output)
            print("------------------------------")
        else:
            print("El puerto se abrió pero no devolvió datos inmediatos. Probemos lectura continua...")
            
            # Bucle de escucha de 5 segundos por si emiten tramas autónomas
            start_time = time.time()
            while time.time() - start_time < 5:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        print(f"LECTURA: {line}")
                time.sleep(0.1)

except Exception as e:
    print(f"Error al conectar con el puerto serie: {e}")
