
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import serial
from flask import Flask, abort, jsonify, request, send_from_directory

# ==========================================
# CONFIGURACION DE LOS DOS ARDUINOS
# ==========================================

PUERTO_AZUCAR = "COM8"
PUERTO_VASO = "COM9"

VELOCIDAD_SERIAL = 9600
GRAMOS_MAXIMOS = 84

TAMANOS_VALIDOS = {
    "Solo", "Doppio", "Short",
    "Tall", "Grande", "Venti"
}

TIEMPO_MAX_AZUCAR = 30
TIEMPO_MAX_VASO = 15

# ==========================================
# SERVIDOR FLASK
# ==========================================

CARPETA = Path(__file__).resolve().parent
app = Flask(__name__)

arduino_azucar = None
arduino_vaso = None

bloqueo_movimiento = threading.Lock()
requiere_revision = False


def esta_conectado(dispositivo):
    return dispositivo is not None and dispositivo.is_open


# ==========================================
# MOSTRAR HTML Y RECURSOS
# ==========================================

@app.get("/")
def inicio():
    return send_from_directory(CARPETA, "index.html")


@app.get("/<path:ruta>")
def recursos_del_proyecto(ruta):
    permitidas = {
        ".json", ".jpg", ".jpeg", ".png",
        ".wav", ".mp3", ".html", ".svg",
        ".webp", ".css", ".js", ".gif"
    }

    if Path(ruta).suffix.lower() not in permitidas:
        abort(404)

    return send_from_directory(CARPETA, ruta)


# ==========================================
# ESTADO DE LOS ARDUINOS
# ==========================================

@app.get("/estado")
def estado():
    return jsonify(
        conectado=(
            esta_conectado(arduino_azucar)
            and esta_conectado(arduino_vaso)
        ),
        conectado_azucar=esta_conectado(arduino_azucar),
        conectado_vaso=esta_conectado(arduino_vaso),
        ocupado=bloqueo_movimiento.locked(),
        requiere_revision=requiere_revision
    )


# ==========================================
# ESPERAR CONFIRMACION DEL ARDUINO
# ==========================================

def esperar_confirmacion(dispositivo, mensaje_esperado, tiempo_maximo):
    limite = time.monotonic() + tiempo_maximo

    while time.monotonic() < limite:
        linea = dispositivo.readline().decode(
            "ascii", errors="replace"
        ).strip()

        if linea == mensaje_esperado:
            return

        if linea.startswith("ERROR:"):
            raise RuntimeError(linea)

    raise TimeoutError(
        f"Sin confirmacion: {mensaje_esperado}"
    )


# ==========================================
# ENVIAR ORDENES A LOS ARDUINOS
# ==========================================

def ejecutar_ordenes(ordenes, respuesta_correcta):
    global requiere_revision

    if requiere_revision:
        return jsonify(
            error="Movimiento anterior sin confirmar. "
                  "Revisa las posiciones y reinicia Python."
        ), 423

    for nombre, dispositivo, *_ in ordenes:
        if not esta_conectado(dispositivo):
            return jsonify(
                error=f"Arduino de {nombre} desconectado. "
                      "Revisa USB/COM y reinicia Python."
            ), 503

    if not bloqueo_movimiento.acquire(blocking=False):
        return jsonify(
            error="Los mecanismos estan ocupados; "
                  "espera a que terminen."
        ), 409

    se_envio_algun_comando = False

    try:
        # Limpiar respuestas anteriores
        for _, dispositivo, _, _, _ in ordenes:
            dispositivo.reset_input_buffer()

        # Enviar instrucciones a ambos Arduino
        for nombre, dispositivo, comando, _, _ in ordenes:
            dispositivo.write(
                (comando + "\n").encode("ascii")
            )
            dispositivo.flush()

            se_envio_algun_comando = True

            print(
                f"[{nombre}] enviado: {comando}",
                flush=True
            )

        # Esperar respuestas en paralelo
        with ThreadPoolExecutor(
            max_workers=len(ordenes)
        ) as pool:

            trabajos = {
                nombre: pool.submit(
                    esperar_confirmacion,
                    dispositivo,
                    confirmacion,
                    timeout
                )
                for nombre, dispositivo, _,
                    confirmacion, timeout in ordenes
            }

            problemas = []

            for nombre, trabajo in trabajos.items():
                try:
                    trabajo.result()

                    print(
                        f"[{nombre}] movimiento finalizado",
                        flush=True
                    )

                except (
                    TimeoutError,
                    RuntimeError,
                    serial.SerialException,
                    OSError
                ) as exc:
                    problemas.append(f"{nombre}: {exc}")

        if problemas:
            requiere_revision = True

            return jsonify(
                error="; ".join(problemas)
                      + ". Revisa ambos mecanismos "
                        "antes de reiniciar Python."
            ), 504

        return jsonify(
            estado="completado",
            **respuesta_correcta
        )

    except (serial.SerialException, OSError) as exc:
        if se_envio_algun_comando:
            requiere_revision = True

        return jsonify(
            error=f"Error USB: {exc}. "
                  "Comprueba ambos mecanismos."
        ), 503

    finally:
        bloqueo_movimiento.release()


# ==========================================
# RECIBIR PEDIDO DE LA TABLET
# ==========================================

@app.post("/pedido")
def pedido():
    datos = request.get_json(silent=True) or {}

    gramos = datos.get("gramos")
    tamano = datos.get("tamano")

    if (
        type(gramos) is not int
        or not 0 <= gramos <= GRAMOS_MAXIMOS
    ):
        return jsonify(
            error="Gramos invalidos: "
                  "debe ser entero entre 0 y 84."
        ), 400

    if (
        not isinstance(tamano, str)
        or tamano not in TAMANOS_VALIDOS
    ):
        return jsonify(
            error="Tamano invalido: Solo, Doppio, "
                  "Short, Tall, Grande o Venti."
        ), 400

    ordenes = [
        (
            "azucar",
            arduino_azucar,
            str(gramos),
            f"LISTO:{gramos}",
            TIEMPO_MAX_AZUCAR
        ),
        (
            "vasos",
            arduino_vaso,
            tamano,
            f"LISTO:{tamano}",
            TIEMPO_MAX_VASO
        )
    ]

    return ejecutar_ordenes(
        ordenes,
        {
            "gramos": gramos,
            "tamano": tamano
        }
    )


# ==========================================
# DEVOLVER AZUCAR A 0 GRAMOS
# ==========================================

@app.post("/azucar/cero")
def azucar_cero():
    ordenes = [
        (
            "azucar",
            arduino_azucar,
            "0",
            "LISTO:0",
            TIEMPO_MAX_AZUCAR
        )
    ]

    return ejecutar_ordenes(
        ordenes,
        {"gramos": 0}
    )


# ==========================================
# CONECTAR PUERTOS USB
# ==========================================

def abrir_puerto(nombre, puerto):
    try:
        dispositivo = serial.Serial(
            puerto,
            VELOCIDAD_SERIAL,
            timeout=0.3,
            write_timeout=2
        )

        print(
            f"Arduino de {nombre}: "
            f"conectado en {puerto}",
            flush=True
        )

        return dispositivo

    except (serial.SerialException, OSError) as exc:
        print(
            f"No se pudo conectar el Arduino "
            f"de {nombre} en {puerto}: {exc}",
            flush=True
        )

        return None


# ==========================================
# INICIAR SERVIDOR
# ==========================================

if __name__ == "__main__":

    if PUERTO_AZUCAR == PUERTO_VASO:
        raise SystemExit(
            "Configura dos puertos COM diferentes."
        )

    arduino_azucar = abrir_puerto(
        "azucar", PUERTO_AZUCAR
    )

    arduino_vaso = abrir_puerto(
        "vasos", PUERTO_VASO
    )

    time.sleep(2)

    print("Desde el PC: http://localhost:5000")
    print(
        "Desde la tablet: "
        "http://IP_DEL_COMPUTADOR:5000"
    )

    try:
        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,
            use_reloader=False
        )

    finally:
        for dispositivo in (
            arduino_azucar,
            arduino_vaso
        ):
            if esta_conectado(dispositivo):
                dispositivo.close()
