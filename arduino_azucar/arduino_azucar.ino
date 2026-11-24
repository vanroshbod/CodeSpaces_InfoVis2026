// arduino_azucar.ino — compatible con servidor.py
// Confirmación serial LISTO:<comando> al terminar cada movimiento.
#include <Servo.h>

Servo motor;

const int PIN_MOTOR = 5;
const int VELOCIDAD = 105;         // Subir
const int VELOCIDAD_INVERSA = 75;  // Bajar
const int DETENIDO = 90;

const float GRAMOS_MAX = 84.0;     // 84 g = vaso lleno

// ---------- CALIBRACIÓN (tiempos medidos) ----------
// Hay 3 alturas: 0 g (fondo), 84 g (vaso lleno) y la ALTURA PARA CAMBIAR
// (más arriba, deja espacio para cambiar el vaso). Esa es la posición de reposo.
const float MS_SUBIR_0_A_84 = 13700.0;
const float MS_BAJAR_84_A_0 = 12000.0;
const float MS_SUBIR_0_A_CAMBIO = 14300.0;
const float MS_BAJAR_CAMBIO_A_0 = 13300.0;

const float MS_POR_GRAMO_SUBIR = MS_SUBIR_0_A_84 / GRAMOS_MAX;
const float MS_POR_GRAMO_BAJAR = MS_BAJAR_84_A_0 / GRAMOS_MAX;

// Margen extra al subir a la altura para cambiar (corrige error acumulado).
// 1.0 = sin margen. Súbelo (ej. 1.05) solo si arriba hay un tope físico;
// si no hay tope, el margen lo deja más alto y después baja de menos.
const float MARGEN_SUBIDA = 1.0;

// La posición física DEBE comenzar en la ALTURA PARA CAMBIAR; no hay sensor.
bool arriba = true;   // true = está en la altura para cambiar
float gramos = 0;     // nivel actual (solo vale si arriba == false)

// Desde el nivel actual hasta la altura para cambiar.
void subirAlturaCambio() {
  if (!arriba) {
    unsigned long t = (unsigned long)((MS_SUBIR_0_A_CAMBIO - gramos * MS_POR_GRAMO_SUBIR) * MARGEN_SUBIDA);
    motor.write(VELOCIDAD);
    delay(t);
    motor.write(DETENIDO);
    delay(600);
  }
  arriba = true;
}

// Desde la altura para cambiar hasta el nivel pedido.
void bajarDesdeCambioHasta(float objetivo) {
  unsigned long t = (unsigned long)(MS_BAJAR_CAMBIO_A_0 - objetivo * MS_POR_GRAMO_BAJAR);
  motor.write(VELOCIDAD_INVERSA);
  delay(t);
  motor.write(DETENIDO);
  gramos = objetivo;
  arriba = false;
}

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(50);
  motor.attach(PIN_MOTOR);
  motor.write(DETENIDO);
}

void loop() {
  if (Serial.available() <= 0) return;

  String mensaje = Serial.readStringUntil('\n');
  mensaje.trim();
  if (mensaje.length() == 0) return;

  // ---- Volver a la altura para cambiar (reposo) ----
  if (mensaje == "ARRIBA") {
    subirAlturaCambio();
    Serial.println("LISTO:ARRIBA");
    return;
  }

  // ---- Comandos de prueba / calibración (modo prueba de la página) ----
  // "?" -> responde "NIVEL:ARRIBA" o "NIVEL:<n>"
  if (mensaje == "?") {
    Serial.print("NIVEL:");
    if (arriba) Serial.println("ARRIBA");
    else Serial.println((int)gramos);
    return;
  }

  // "SUBIR:<ms>" / "BAJAR:<ms>": mueve ese tiempo exacto SIN cambiar la
  // posición que recuerda el Arduino. Después usa "AQUI:ARRIBA".
  if (mensaje.startsWith("SUBIR:") || mensaje.startsWith("BAJAR:")) {
    bool subir = mensaje.startsWith("SUBIR:");
    unsigned long ms = mensaje.substring(6).toInt();
    if (ms > 20000) {
      Serial.println("ERROR:Maximo 20000 ms");
      return;
    }
    motor.write(subir ? VELOCIDAD : VELOCIDAD_INVERSA);
    delay(ms);
    motor.write(DETENIDO);
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  // "AQUI:ARRIBA" o "AQUI:<n>": no se mueve, solo fija la posición.
  if (mensaje.startsWith("AQUI:")) {
    String valor = mensaje.substring(5);
    if (valor == "ARRIBA") {
      arriba = true;
    } else {
      float n = valor.toFloat();
      if (n < 0 || n > GRAMOS_MAX) {
        Serial.println("ERROR:Gramos fuera de rango");
        return;
      }
      gramos = n;
      arriba = false;
    }
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  // ---- Pedido: un número de gramos ----
  for (unsigned int i = 0; i < mensaje.length(); i++) {
    if (mensaje[i] < '0' || mensaje[i] > '9') {
      Serial.println("ERROR:Formato invalido");
      return;
    }
  }

  float nuevos_gramos = mensaje.toFloat();
  if (nuevos_gramos < 0 || nuevos_gramos > GRAMOS_MAX) {
    Serial.println("ERROR:Gramos fuera de rango");
    return;
  }

  if (arriba || nuevos_gramos != gramos) {
    // FASE 1: subir a la altura para cambiar (si no está ahí).
    subirAlturaCambio();
    // FASE 2: bajar desde ahí hasta el nivel de la bebida.
    bajarDesdeCambioHasta(nuevos_gramos);
  }

  // Confirmación de finalización del programa, no de posición física.
  Serial.print("LISTO:");
  Serial.println((int)nuevos_gramos);
}
