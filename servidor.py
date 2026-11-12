# servidor.py — tablet (navegador) -> Wi-Fi -> Python -> USB -> Arduino Leonardo
# Requiere: py -m pip install flask pyserial
# Úsalo solo en una red local de confianza, nunca como servidor público.

import threading
import time
from pathlib import Path

import serial
from flask import Flask, abort, jsonify, request, send_from_directory

# AJUSTAR: consulta el COM real en Arduino IDE > Herramientas > Puerto.
PUERTO_ARDUINO = "COM9"
BAUDIOS = 9600
MAX_GRAMOS = 84
ESPERA_MAXIMA_SEGUNDOS = 30

CARPETA_PROYECTO = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)

# Solo este servidor debe tener abierto el puerto USB.
arduino = None
error_usb = False
requiere_revision = False
movimiento_en_curso = threading.Lock()


@app.get("/")
def pagina_principal():
    return send_from_directory(CARPETA_PROYECTO, "index.html")


@app.get("/<path:archivo>")
def recursos(archivo):
    # Archivos usados por el HTML: JSON, imágenes, sonidos, V1.html, etc.
    extensiones_permitidas = {
        ".html", ".json", ".js", ".css", ".png", ".jpg", ".jpeg",
        ".svg", ".webp", ".gif", ".ico", ".mp3", ".wav", ".ogg",
        ".woff", ".woff2"
    }
    if Path(archivo).suffix.lower() not in extensiones_permitidas:
        abort(404)
    return send_from_directory(CARPETA_PROYECTO, archivo)


@app.get("/estado")
def estado():
    conectado = bool(arduino and arduino.is_open and not error_usb)
    return jsonify({
        "conectado": conectado,
        "ocupado": movimiento_en_curso.locked(),
        "requiere_revision": requiere_revision,
    })


@app.post("/pedido")
def pedido():
    global error_usb, requiere_revision

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="Envía un JSON con el campo 'gramos'."), 400
    gramos = datos.get("gramos")

    # Solo enteros (sin booleanos) entre 0 y 84: mismo rango que el HTML.
    if type(gramos) is not int or not 0 <= gramos <= MAX_GRAMOS:
        return jsonify(error="'gramos' debe ser un entero entre 0 y 84."), 400

    if requiere_revision:
        return jsonify(error="Revisa la posición física del mecanismo antes de continuar y reinicia Python."), 423
    if not (arduino and arduino.is_open and not error_usb):
        return jsonify(error="Arduino desconectado. Comprueba el COM y reinicia Python."), 503

    # Bloquear pedidos simultáneos, incluso desde dos tablets a la vez.
    if not movimiento_en_curso.acquire(blocking=False):
        return jsonify(error="El motor está ocupado. Espera que finalice."), 409

    try:
        # El sketch adjunto responde LISTO:<gramos> cuando termina.
        arduino.reset_input_buffer()
        arduino.write(f"{gramos}\n".encode("ascii"))
        arduino.flush()
        print(f"Pedido enviado: {gramos} g", flush=True)

        final = time.monotonic() + ESPERA_MAXIMA_SEGUNDOS
        while time.monotonic() < final:
            recibido = arduino.readline().decode("ascii", errors="replace").strip()
            if recibido == f"LISTO:{gramos}":
                print(f"Arduino terminó: {gramos} g", flush=True)
                return jsonify(estado="completado", gramos=gramos)
            if recibido.startswith("ERROR:"):
                requiere_revision = True
                return jsonify(error="El Arduino rechazó el comando: " + recibido), 422

        requiere_revision = True
        return jsonify(error="No llegó LISTO desde el Arduino. Comprueba el motor antes de reiniciar."), 504

    except (serial.SerialException, OSError) as exc:
        error_usb = True
        requiere_revision = True
        print(f"Error USB: {exc}", flush=True)
        return jsonify(error="Se perdió la conexión USB. Revisa el mecanismo y reinicia Python."), 503

    finally:
        movimiento_en_curso.release()


if __name__ == "__main__":
    print("IMPORTANTE: coloca el mecanismo físicamente en 0 g antes de iniciar.")
    try:
        arduino = serial.Serial(
            port=PUERTO_ARDUINO,
            baudrate=BAUDIOS,
            timeout=0.35,
            write_timeout=2,
        )
    except serial.SerialException as exc:
        raise SystemExit(
            f"No se pudo abrir {PUERTO_ARDUINO}: {exc}\n"
            "Revisa el puerto COM y cierra el Monitor Serie/Plotter Serie del IDE Arduino."
        )

    # Tiempo de preparación del puerto del Arduino Leonardo.
    time.sleep(2)
    print(f"Arduino conectado en {PUERTO_ARDUINO} a {BAUDIOS} baudios")
    print("En el PC: http://localhost:5000")
    print("En la tablet: http://IP_DEL_PC:5000 (misma red Wi-Fi)")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False,
                use_reloader=False, threaded=True)
    finally:
        arduino.close()
