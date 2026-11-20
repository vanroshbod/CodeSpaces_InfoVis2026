#include <Servo.h>

// ==========================================================
// ARDUINO DEL AZUCAR (servo de rotacion continua, sin sensores)
// ----------------------------------------------------------
// La posicion de REPOSO es ARRIBA (tope = vaso lleno = 84 g).
// Estando arriba, el selector de vasos puede moverse sin chocar.
//
// Para cada pedido:
//   1) Si no esta arriba, sube hasta el tope (corrige error acumulado).
//   2) Baja desde el tope hasta el nivel que corresponde a los gramos.
//
// El nivel se mide desde el fondo del vaso y es PROPORCIONAL a los gramos:
//   84 g (la bebida con mas azucar del menu) = vaso lleno = no baja nada.
//   42 g = mitad del vaso.   0 g = baja hasta el fondo.
//
// Comandos por Serial (terminados en '\n'):
//   "<entero 0-84>"  -> ir a ese nivel.      Responde "LISTO:<n>"
//   "ARRIBA"         -> volver al tope.       Responde "LISTO:ARRIBA"
//   Pruebas: "?", "SUBIR:<ms>", "BAJAR:<ms>", "AQUI:ARRIBA", "AQUI:<n>"
//
// IMPORTANTE: al encender, el mecanismo debe estar fisicamente ARRIBA.
// ==========================================================

Servo motor;

const int PIN_MOTOR = 5;
const int VELOCIDAD = 110;         // Velocidad para subir
const int VELOCIDAD_INVERSA = 75;  // Velocidad para bajar
const int DETENIDO = 90;

// DATOS FISICOS REALES (se conservan los valores calibrados)
const float ALTURA_MAX_CM = 15.0;
const float GRAMOS_MAX = 84.0;

// CALIBRACION
const float CM_BAJADA_10S = 16.4;
const float CM_SUBIDA_10S = 15.8;
const float TIEMPO_PRUEBA_MS = 10000.0;

// Margen extra al subir al tope para absorber el error acumulado
// (antes se usaba al bajar al fondo). Poner 1.0 si choca contra el tope.
const float MARGEN_TOPE = 1.05;

const float CM_POR_GRAMO = ALTURA_MAX_CM / GRAMOS_MAX;
const float MS_POR_CM_BAJAR = TIEMPO_PRUEBA_MS / CM_BAJADA_10S;
const float MS_POR_CM_SUBIR = TIEMPO_PRUEBA_MS / CM_SUBIDA_10S;
const float MS_POR_GRAMO_BAJAR = CM_POR_GRAMO * MS_POR_CM_BAJAR;
const float MS_POR_GRAMO_SUBIR = CM_POR_GRAMO * MS_POR_CM_SUBIR;

// Nivel actual expresado en gramos (altura desde el fondo).
// Parte en GRAMOS_MAX porque al encender esta arriba.
float nivel = GRAMOS_MAX;

void subirAlTope() {
  if (nivel < GRAMOS_MAX) {
    unsigned long tiempoSubir =
      (unsigned long)((GRAMOS_MAX - nivel) * MS_POR_GRAMO_SUBIR * MARGEN_TOPE);
    motor.write(VELOCIDAD);
    delay(tiempoSubir);
    motor.write(DETENIDO);
    delay(600);
  }
  nivel = GRAMOS_MAX;
}

void bajarDesdeElTopeHasta(float objetivo) {
  // Se asume que ya esta en el tope.
  unsigned long tiempoBajar =
    (unsigned long)((GRAMOS_MAX - objetivo) * MS_POR_GRAMO_BAJAR);
  if (tiempoBajar > 0) {
    motor.write(VELOCIDAD_INVERSA);
    delay(tiempoBajar);
    motor.write(DETENIDO);
  }
  nivel = objetivo;
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

  // ---- Volver arriba (posicion de reposo) ----
  if (mensaje == "ARRIBA") {
    subirAlTope();
    Serial.println("LISTO:ARRIBA");
    return;
  }

  // ---- Comandos de prueba / calibracion ----
  // "?" -> responde "NIVEL:<n>" (nivel logico actual)
  if (mensaje == "?") {
    Serial.print("NIVEL:");
    Serial.println((int)nivel);
    return;
  }

  // "SUBIR:<ms>" / "BAJAR:<ms>": mueve ese tiempo exacto SIN cambiar el
  // nivel logico. Sirve para calibrar. Despues usa "AQUI:ARRIBA".
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

  // "AQUI:ARRIBA" o "AQUI:<n>": no se mueve, solo fija el nivel logico.
  if (mensaje.startsWith("AQUI:")) {
    String valor = mensaje.substring(5);
    float n = (valor == "ARRIBA") ? GRAMOS_MAX : valor.toFloat();
    if (n < 0 || n > GRAMOS_MAX) {
      Serial.println("ERROR:Gramos fuera de rango");
      return;
    }
    nivel = n;
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  // ---- Ir a un nivel: aceptar solo enteros ----
  for (unsigned int i = 0; i < mensaje.length(); i++) {
    if (mensaje[i] < '0' || mensaje[i] > '9') {
      Serial.println("ERROR:Formato invalido");
      return;
    }
  }

  float nuevosGramos = mensaje.toFloat();
  if (nuevosGramos < 0 || nuevosGramos > GRAMOS_MAX) {
    Serial.println("ERROR:Gramos fuera de rango");
    return;
  }

  if (nuevosGramos != nivel) {
    // FASE 1: subir al tope (si no esta ahi) para partir siempre desde arriba.
    subirAlTope();
    // FASE 2: bajar desde arriba hasta el nivel de la bebida.
    bajarDesdeElTopeHasta(nuevosGramos);
  }

  // Avisa a Python que termino el movimiento.
  // No garantiza posicion fisica exacta: eso requeriria un sensor.
  Serial.print("LISTO:");
  Serial.println((int)nuevosGramos);
}
