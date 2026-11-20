# servidor.py — tablet (navegador) -> Wi-Fi -> Python -> USB -> Arduino Leonardo (azúcar)
# Requiere: py -m pip install flask pyserial
# Úsalo solo en una red local de confianza, nunca como servidor público.

import re
import threading
import time
from pathlib import Path

import serial
from flask import Flask, abort, jsonify, request, send_from_directory

# AJUSTAR: consulta el COM real en Arduino IDE > Herramientas > Puerto.
PUERTO_ARDUINO = "COM9"
BAUDIOS = 9600
MAX_GRAMOS = 84
ESPERA_MAXIMA_SEGUNDOS = 40   # peor caso: subir (~12 s) + bajar (~13 s)

CARPETA_PROYECTO = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)

# Solo este servidor debe tener abierto el puerto USB.
arduino = None
requiere_revision = False
movimiento_en_curso = threading.Lock()


# ==========================================
# PÁGINA Y RECURSOS
# ==========================================

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


# ==========================================
# CONEXIÓN USB
# ==========================================

def abrir_puerto():
    try:
        dispositivo = serial.Serial(
            port=PUERTO_ARDUINO,
            baudrate=BAUDIOS,
            timeout=0.35,
            write_timeout=2,
        )
        print(f"Arduino conectado en {PUERTO_ARDUINO} a {BAUDIOS} baudios", flush=True)
        return dispositivo
    except (serial.SerialException, OSError) as exc:
        print(
            f"No se pudo abrir {PUERTO_ARDUINO}: {exc}\n"
            "Revisa el cable/puerto COM y cierra el Monitor Serie del IDE Arduino.\n"
            "Luego usa 'Reintentar conexión' en el modo prueba de la página.",
            flush=True,
        )
        return None


def esta_conectado():
    return arduino is not None and arduino.is_open


def cerrar_puerto(motivo):
    """Cierra el puerto si se cayó el cable, para que /estado lo muestre."""
    global arduino
    try:
        if arduino is not None:
            arduino.close()
    except Exception:
        pass
    arduino = None
    print(f"Puerto cerrado: {motivo}", flush=True)


def verificar_conexion():
    """Detecta un cable desconectado aunque el puerto siga 'abierto'."""
    if arduino is None or movimiento_en_curso.locked():
        return
    try:
        _ = arduino.in_waiting
    except (serial.SerialException, OSError) as exc:
        cerrar_puerto(exc)


@app.get("/estado")
def estado():
    verificar_conexion()
    return jsonify({
        "conectado": esta_conectado(),
        "ocupado": movimiento_en_curso.locked(),
        "requiere_revision": requiere_revision,
    })


# ==========================================
# ENVIAR UN COMANDO Y ESPERAR RESPUESTA
# ==========================================

def enviar_comando(comando, timeout=ESPERA_MAXIMA_SEGUNDOS,
                   marcar_revision=True, prefijo_respuesta=None):
    """Envía un comando y espera LISTO:<comando> (o una línea con el prefijo
    indicado). Devuelve (respuesta_json, codigo_http)."""
    global requiere_revision

    if not esta_conectado():
        return {"error": "Arduino desconectado. Revisa el cable y usa "
                         "'Reintentar conexión' en el modo prueba."}, 503

    # Bloquear pedidos simultáneos, incluso desde dos tablets a la vez.
    if not movimiento_en_curso.acquire(blocking=False):
        return {"error": "El motor está ocupado. Espera que finalice."}, 409

    try:
        arduino.reset_input_buffer()
        arduino.write(f"{comando}\n".encode("ascii"))
        arduino.flush()
        print(f"Enviado: {comando}", flush=True)

        esperado = f"LISTO:{comando}"
        final = time.monotonic() + timeout
        while time.monotonic() < final:
            recibido = arduino.readline().decode("ascii", errors="replace").strip()
            if recibido == esperado or (
                prefijo_respuesta and recibido.startswith(prefijo_respuesta)
            ):
                print(f"Arduino respondió: {recibido}", flush=True)
                return {"estado": "completado", "respuesta": recibido}, 200
            if recibido.startswith("ERROR:"):
                if marcar_revision:
                    requiere_revision = True
                return {"error": "El Arduino rechazó el comando: " + recibido}, 422

        if marcar_revision:
            requiere_revision = True
        return {"error": "No llegó LISTO desde el Arduino. "
                         "Comprueba el motor antes de seguir."}, 504

    except (serial.SerialException, OSError) as exc:
        cerrar_puerto(exc)
        if marcar_revision:
            requiere_revision = True
        return {"error": "Se perdió la conexión USB. Revisa el cable y usa "
                         "'Reintentar conexión' en el modo prueba."}, 503

    finally:
        movimiento_en_curso.release()


def bloqueado_por_revision():
    return jsonify(error="Revisa la posición física del mecanismo y usa "
                         "'Desbloquear' en el modo prueba."), 423


# ==========================================
# PEDIDO NORMAL
# ==========================================

@app.post("/pedido")
def pedido():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="Envía un JSON con el campo 'gramos'."), 400
    gramos = datos.get("gramos")

    # Solo enteros (sin booleanos) entre 0 y 84: mismo rango que el HTML.
    if type(gramos) is not int or not 0 <= gramos <= MAX_GRAMOS:
        return jsonify(error="'gramos' debe ser un entero entre 0 y 84."), 400

    if requiere_revision:
        return bloqueado_por_revision()

    respuesta, codigo = enviar_comando(str(gramos))
    if codigo == 200:
        respuesta["gramos"] = gramos
    return jsonify(respuesta), codigo


@app.post("/azucar/arriba")
def azucar_arriba():
    """Sube el mecanismo a la altura para cambiar (posición de reposo)."""
    if requiere_revision:
        return bloqueado_por_revision()
    respuesta, codigo = enviar_comando("ARRIBA")
    return jsonify(respuesta), codigo


# ==========================================
# MODO PRUEBA / CALIBRACIÓN
# ==========================================

PATRON_PRUEBA = re.compile(r"^(\d{1,2}|ARRIBA|\?|(SUBIR|BAJAR):\d{1,5}|AQUI:(\d{1,2}|ARRIBA))$")


@app.post("/prueba")
def prueba():
    datos = request.get_json(silent=True) or {}
    comando = str(datos.get("comando", "")).strip()

    if not PATRON_PRUEBA.match(comando):
        return jsonify(error=f"Comando no permitido: {comando}"), 400

    numero = re.search(r"(\d+)$", comando)
    if numero and (comando.isdigit() or comando.startswith("AQUI:")):
        if int(numero.group(1)) > MAX_GRAMOS:
            return jsonify(error=f"Gramos entre 0 y {MAX_GRAMOS}."), 400

    timeout = ESPERA_MAXIMA_SEGUNDOS
    if comando.startswith(("SUBIR:", "BAJAR:")):
        ms = int(numero.group(1))
        if ms > 20000:
            return jsonify(error="Máximo 20000 ms por prueba."), 400
        timeout = ms / 1000 + 5

    respuesta, codigo = enviar_comando(
        comando, timeout=timeout, marcar_revision=False,
        prefijo_respuesta="NIVEL:" if comando == "?" else None,
    )
    return jsonify(respuesta), codigo


@app.post("/reconectar")
def reconectar():
    """Vuelve a abrir el puerto si el cable se desconectó."""
    global arduino
    verificar_conexion()
    reconectados = []
    if not esta_conectado() and not movimiento_en_curso.locked():
        arduino = abrir_puerto()
        if arduino:
            reconectados.append("azucar")
            time.sleep(1)
    return jsonify(reconectados=reconectados, conectado=esta_conectado())


@app.post("/desbloquear")
def desbloquear():
    """Quita el bloqueo por movimiento sin confirmar (ya revisaste a mano)."""
    global requiere_revision
    requiere_revision = False
    return jsonify(estado="desbloqueado")


# ==========================================
# INICIAR
# ==========================================

if __name__ == "__main__":
    print("IMPORTANTE: coloca el mecanismo físicamente en la ALTURA PARA CAMBIAR antes de iniciar.")

    # Si no conecta, el servidor igual parte: se puede reintentar desde la página.
    arduino = abrir_puerto()

    # Tiempo de preparación del puerto del Arduino Leonardo.
    time.sleep(2)
    print("En el PC: http://localhost:5000")
    print("En la tablet: http://IP_DEL_PC:5000 (misma red Wi-Fi)")
    try:
        app.run(host="0.0.0.0", port=5000, debug=False,
                use_reloader=False, threaded=True)
    finally:
        if esta_conectado():
            arduino.close()
