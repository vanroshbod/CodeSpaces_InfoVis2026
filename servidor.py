from pathlib import Path
import threading
import time

import serial
from flask import Flask, abort, jsonify, request, send_from_directory

# ==========================================
# CONFIGURACION DE LOS DOS ARDUINOS
# ==========================================

PUERTO_AZUCAR = "COM11"
PUERTO_VASO = "COM9"

VELOCIDAD_SERIAL = 9600
GRAMOS_MAXIMOS = 84   # bebida con mas azucar del menu = vaso lleno

TAMANOS_VALIDOS = {
    "Solo", "Doppio", "Short",
    "Tall", "Grande", "Venti"
}

TIEMPO_MAX_AZUCAR = 30
TIEMPO_MAX_VASO = 20   # ahora se detiene en cada vaso, tarda un poco mas

# ==========================================
# FLUJO DEL PEDIDO
# ------------------------------------------
# 1) POST /vaso {tamano}
#      - Si el azucar no esta arriba, primero lo sube (para no chocar).
#      - Mueve el selector de vasos y espera LISTO.
#    La pagina hace esto apenas se elige el tamano, mientras el
#    usuario sigue eligiendo bebida y leche.
# 2) POST /pedido {gramos, tamano}
#      - Solo se acepta si el vaso YA llego a ese tamano y no se esta
#        moviendo. Recien ahi se manda el nivel al Arduino del azucar.
# 3) POST /azucar/arriba  -> vuelve el azucar a su posicion de reposo.
# ==========================================

CARPETA = Path(__file__).resolve().parent
app = Flask(__name__)

arduino_azucar = None
arduino_vaso = None

bloqueo_azucar = threading.Lock()
bloqueo_vaso = threading.Lock()
bloqueo_estado = threading.Lock()

requiere_revision = False
azucar_arriba = True          # al encender el mecanismo debe estar arriba
tamano_vaso_actual = "Short"  # ultimo tamano CONFIRMADO (al encender: Short)
tamano_vaso_destino = None    # tamano al que se esta moviendo (si se mueve)


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

def verificar_conexion(nombre):
    """Detecta un cable desconectado aunque el puerto siga 'abierto'.
    Solo se revisa si ese Arduino no esta en medio de un movimiento."""
    disp = arduino_azucar if nombre == "azucar" else arduino_vaso
    bloqueo = bloqueo_azucar if nombre == "azucar" else bloqueo_vaso
    if disp is None or bloqueo.locked():
        return
    try:
        _ = disp.in_waiting
    except (serial.SerialException, OSError) as exc:
        cerrar_si_se_cayo(nombre, exc)


@app.get("/estado")
def estado():
    verificar_conexion("azucar")
    verificar_conexion("vasos")
    vaso_moviendo = bloqueo_vaso.locked()
    azucar_moviendo = bloqueo_azucar.locked()
    return jsonify(
        conectado=(
            esta_conectado(arduino_azucar)
            and esta_conectado(arduino_vaso)
        ),
        conectado_azucar=esta_conectado(arduino_azucar),
        conectado_vaso=esta_conectado(arduino_vaso),
        ocupado=vaso_moviendo or azucar_moviendo,
        vaso_moviendo=vaso_moviendo,
        azucar_moviendo=azucar_moviendo,
        azucar_arriba=azucar_arriba,
        tamano_vaso=tamano_vaso_actual,
        tamano_vaso_destino=tamano_vaso_destino,
        requiere_revision=requiere_revision
    )


# ==========================================
# ENVIAR UNA ORDEN Y ESPERAR CONFIRMACION
# ==========================================

def esperar_confirmacion(dispositivo, mensaje_esperado, tiempo_maximo,
                         prefijos=None):
    limite = time.monotonic() + tiempo_maximo

    while time.monotonic() < limite:
        linea = dispositivo.readline().decode(
            "ascii", errors="replace"
        ).strip()

        if linea == mensaje_esperado:
            return linea

        if prefijos and linea.startswith(tuple(prefijos)):
            return linea

        if linea.startswith("ERROR:"):
            raise RuntimeError(linea)

    raise TimeoutError(
        f"Sin confirmacion: {mensaje_esperado}"
    )


def cerrar_si_se_cayo(nombre, exc):
    """Si el USB se desconecto, cierra el puerto para que /estado lo muestre."""
    global arduino_azucar, arduino_vaso
    if not isinstance(exc, (serial.SerialException, OSError)):
        return
    disp = arduino_azucar if nombre == "azucar" else arduino_vaso
    try:
        if disp is not None:
            disp.close()
    except Exception:
        pass
    if nombre == "azucar":
        arduino_azucar = None
    else:
        arduino_vaso = None
    print(f"[{nombre}] puerto cerrado: {exc}", flush=True)


def enviar_y_esperar(nombre, dispositivo, comando, confirmacion, timeout,
                     marcar_revision=True, prefijos=None):
    """Manda un comando y bloquea hasta recibir la confirmacion.
    Si algo falla despues de enviar, marca requiere_revision."""
    global requiere_revision

    if not esta_conectado(dispositivo):
        raise ConnectionError(
            f"Arduino de {nombre} desconectado. "
            "Revisa el cable y usa 'Reintentar conexion'."
        )

    try:
        dispositivo.reset_input_buffer()
        dispositivo.write((comando + "\n").encode("ascii"))
        dispositivo.flush()
        print(f"[{nombre}] enviado: {comando}", flush=True)
        respuesta = esperar_confirmacion(
            dispositivo, confirmacion, timeout, prefijos
        )
    except (TimeoutError, RuntimeError,
            serial.SerialException, OSError) as exc:
        cerrar_si_se_cayo(nombre, exc)
        if marcar_revision:
            requiere_revision = True
        raise RuntimeError(
            f"{nombre}: {exc}. Revisa el mecanismo."
        ) from exc

    print(f"[{nombre}] respuesta: {respuesta}", flush=True)
    return respuesta


def subir_azucar():
    """Sube el azucar al tope. Debe llamarse con bloqueo_azucar tomado."""
    global azucar_arriba
    enviar_y_esperar(
        "azucar", arduino_azucar, "ARRIBA",
        "LISTO:ARRIBA", TIEMPO_MAX_AZUCAR
    )
    azucar_arriba = True


def error_revision():
    return jsonify(
        error="Movimiento anterior sin confirmar. "
              "Revisa las posiciones y reinicia Python."
    ), 423


# ==========================================
# PASO 1: MOVER EL SELECTOR DE VASOS
# ==========================================

@app.post("/vaso")
def mover_vaso():
    global tamano_vaso_actual, tamano_vaso_destino

    if requiere_revision:
        return error_revision()

    datos = request.get_json(silent=True) or {}
    tamano = datos.get("tamano")

    if not isinstance(tamano, str) or tamano not in TAMANOS_VALIDOS:
        return jsonify(
            error="Tamano invalido: Solo, Doppio, "
                  "Short, Tall, Grande o Venti."
        ), 400

    for nombre, disp in (("vasos", arduino_vaso),
                         ("azucar", arduino_azucar)):
        if not esta_conectado(disp):
            return jsonify(
                error=f"Arduino de {nombre} desconectado. "
                      "Revisa el cable y usa 'Reintentar conexion'."
            ), 503

    # Se necesitan los dos: el azucar no puede moverse mientras gira el vaso.
    if not bloqueo_vaso.acquire(blocking=False):
        return jsonify(
            error="El selector de vasos ya se esta moviendo."
        ), 409
    if not bloqueo_azucar.acquire(blocking=False):
        bloqueo_vaso.release()
        return jsonify(
            error="El azucar se esta moviendo; espera."
        ), 409

    try:
        with bloqueo_estado:
            tamano_vaso_destino = tamano
            tamano_vaso_actual = None   # posicion intermedia mientras se mueve

        if not azucar_arriba:
            subir_azucar()

        enviar_y_esperar(
            "vasos", arduino_vaso, tamano,
            f"LISTO:{tamano}", TIEMPO_MAX_VASO
        )

        with bloqueo_estado:
            tamano_vaso_actual = tamano

        return jsonify(estado="completado", tamano=tamano)

    except (RuntimeError, ConnectionError,
            serial.SerialException, OSError) as exc:
        return jsonify(error=str(exc)), 504

    finally:
        with bloqueo_estado:
            tamano_vaso_destino = None
        bloqueo_azucar.release()
        bloqueo_vaso.release()


# ==========================================
# PASO 2: BAJAR EL AZUCAR AL NIVEL DEL PEDIDO
# ==========================================

@app.post("/pedido")
def pedido():
    global azucar_arriba

    if requiere_revision:
        return error_revision()

    datos = request.get_json(silent=True) or {}
    gramos = datos.get("gramos")
    tamano = datos.get("tamano")

    if (
        type(gramos) is not int
        or not 0 <= gramos <= GRAMOS_MAXIMOS
    ):
        return jsonify(
            error=f"Gramos invalidos: debe ser entero "
                  f"entre 0 y {GRAMOS_MAXIMOS}."
        ), 400

    # El azucar solo se manda cuando el vaso ya termino de moverse
    # y quedo en el tamano del pedido.
    if bloqueo_vaso.locked():
        return jsonify(
            error="El vaso todavia se esta moviendo; "
                  "espera a que se detenga."
        ), 409

    if tamano != tamano_vaso_actual:
        return jsonify(
            error=f"El vaso no esta en {tamano}. "
                  "Vuelve a seleccionar el tamano."
        ), 409

    if not bloqueo_azucar.acquire(blocking=False):
        return jsonify(
            error="El azucar se esta moviendo; espera."
        ), 409

    try:
        azucar_arriba = False   # desde aqui puede quedar abajo
        enviar_y_esperar(
            "azucar", arduino_azucar, str(gramos),
            f"LISTO:{gramos}", TIEMPO_MAX_AZUCAR
        )
        azucar_arriba = (gramos == GRAMOS_MAXIMOS)

        return jsonify(
            estado="completado",
            gramos=gramos,
            tamano=tamano
        )

    except (RuntimeError, ConnectionError,
            serial.SerialException, OSError) as exc:
        return jsonify(error=str(exc)), 504

    finally:
        bloqueo_azucar.release()


# ==========================================
# VOLVER EL AZUCAR ARRIBA (REPOSO)
# ==========================================

@app.post("/azucar/arriba")
def azucar_a_reposo():
    if requiere_revision:
        return error_revision()

    if not bloqueo_azucar.acquire(blocking=False):
        return jsonify(
            error="El azucar se esta moviendo; espera."
        ), 409

    try:
        subir_azucar()
        return jsonify(estado="completado", azucar_arriba=True)

    except (RuntimeError, ConnectionError,
            serial.SerialException, OSError) as exc:
        return jsonify(error=str(exc)), 504

    finally:
        bloqueo_azucar.release()



# ==========================================
# MODO PRUEBA / CALIBRACION
# ------------------------------------------
# Permite usar cada Arduino por separado (aunque el otro no
# este conectado) y reconectar sin reiniciar Python.
# OJO: aqui NO se sube el azucar automaticamente antes de mover
# los vasos. Revisa que no choquen.
# ==========================================

import re

PATRONES_PRUEBA = {
    "vasos": re.compile(
        r"^(Solo|Doppio|Short|Tall|Grande|Venti|\+|-|\?"
        r"|(DER|IZQ):\d{1,5}"
        r"|AQUI:(Solo|Doppio|Short|Tall|Grande|Venti))$"
    ),
    "azucar": re.compile(
        r"^(\d{1,2}|ARRIBA|\?|(SUBIR|BAJAR):\d{1,5}"
        r"|AQUI:(ARRIBA|\d{1,2}))$"
    ),
}


def tiempo_maximo_prueba(nombre, comando):
    m = re.search(r":(\d+)$", comando)
    if m and not comando.startswith("AQUI"):
        return int(m.group(1)) / 1000 + 5
    return TIEMPO_MAX_VASO if nombre == "vasos" else TIEMPO_MAX_AZUCAR


def actualizar_estado_tras_prueba(nombre, comando):
    global tamano_vaso_actual, azucar_arriba
    if nombre == "vasos":
        if comando in TAMANOS_VALIDOS:
            tamano_vaso_actual = comando
        elif comando.startswith("AQUI:"):
            tamano_vaso_actual = comando.split(":", 1)[1]
        elif comando != "?":
            tamano_vaso_actual = None   # posicion sin nombre conocido
    else:
        if comando in ("ARRIBA", "AQUI:ARRIBA"):
            azucar_arriba = True
        elif comando.isdigit():
            azucar_arriba = int(comando) == GRAMOS_MAXIMOS
        elif comando.startswith("AQUI:"):
            azucar_arriba = int(comando.split(":")[1]) == GRAMOS_MAXIMOS
        elif comando != "?":
            azucar_arriba = False       # movimiento manual: posicion incierta


@app.post("/prueba")
def prueba():
    datos = request.get_json(silent=True) or {}
    nombre = datos.get("arduino")
    comando = str(datos.get("comando", "")).strip()

    if nombre not in PATRONES_PRUEBA:
        return jsonify(error="Arduino invalido: 'vasos' o 'azucar'."), 400
    if not PATRONES_PRUEBA[nombre].match(comando):
        return jsonify(error=f"Comando no permitido: {comando}"), 400
    if comando.isdigit() and not 0 <= int(comando) <= GRAMOS_MAXIMOS:
        return jsonify(error=f"Gramos entre 0 y {GRAMOS_MAXIMOS}."), 400
    m = re.search(r":(\d+)$", comando)
    if m and not comando.startswith("AQUI") and int(m.group(1)) > 20000:
        return jsonify(error="Maximo 20000 ms por prueba."), 400

    disp = arduino_azucar if nombre == "azucar" else arduino_vaso
    bloqueo = bloqueo_azucar if nombre == "azucar" else bloqueo_vaso

    if not bloqueo.acquire(blocking=False):
        return jsonify(error=f"El Arduino de {nombre} esta ocupado."), 409

    try:
        prefijos = None
        if comando == "?":
            prefijos = ["POS:"] if nombre == "vasos" else ["NIVEL:"]
        respuesta = enviar_y_esperar(
            nombre, disp, comando, f"LISTO:{comando}",
            tiempo_maximo_prueba(nombre, comando),
            marcar_revision=False, prefijos=prefijos
        )
        actualizar_estado_tras_prueba(nombre, comando)
        return jsonify(estado="completado", respuesta=respuesta)

    except (RuntimeError, ConnectionError,
            serial.SerialException, OSError) as exc:
        return jsonify(error=str(exc)), 504

    finally:
        bloqueo.release()


@app.post("/reconectar")
def reconectar():
    """Vuelve a abrir los puertos que esten cerrados (cable reconectado)."""
    global arduino_azucar, arduino_vaso, tamano_vaso_actual, azucar_arriba
    verificar_conexion("azucar")
    verificar_conexion("vasos")
    reconectados = []

    if not esta_conectado(arduino_azucar) and not bloqueo_azucar.locked():
        arduino_azucar = abrir_puerto("azucar", PUERTO_AZUCAR)
        if arduino_azucar:
            # Al reconectar el cable el Leonardo se reinicia y asume ARRIBA.
            azucar_arriba = True
            reconectados.append("azucar")

    if not esta_conectado(arduino_vaso) and not bloqueo_vaso.locked():
        arduino_vaso = abrir_puerto("vasos", PUERTO_VASO)
        if arduino_vaso:
            # Se reinicia en POSICION_INICIAL (Short).
            tamano_vaso_actual = "Short"
            reconectados.append("vasos")

    if reconectados:
        time.sleep(1)

    return jsonify(
        reconectados=reconectados,
        conectado_azucar=esta_conectado(arduino_azucar),
        conectado_vaso=esta_conectado(arduino_vaso)
    )


@app.post("/desbloquear")
def desbloquear():
    """Quita el bloqueo por movimiento sin confirmar (ya revisaste a mano)."""
    global requiere_revision
    requiere_revision = False
    return jsonify(estado="desbloqueado")

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

    print(
        "ANTES DE SEGUIR: el azucar debe estar ARRIBA y el "
        "selector de vasos en el vaso Short.",
        flush=True
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
            use_reloader=False,
            threaded=True   # /estado responde mientras se mueve el vaso
        )

    finally:
        for dispositivo in (
            arduino_azucar,
            arduino_vaso
        ):
            if esta_conectado(dispositivo):
                dispositivo.close()
