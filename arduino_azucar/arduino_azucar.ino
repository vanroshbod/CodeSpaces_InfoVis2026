// arduino_azucar.ino — compatible con servidor.py
// Es tu lógica calibrada, con confirmación serial LISTO:<gramos>.
#include <Servo.h>

Servo motor;

const int PIN_MOTOR = 5;
const int VELOCIDAD = 75;         // Subir
const int VELOCIDAD_INVERSA = 105;  // Bajar
const int DETENIDO = 90;

const float ALTURA_MAX_CM = 15.0;
const float GRAMOS_MAX = 84.0;
const float CM_BAJADA_10S = 16.4;
const float CM_SUBIDA_10S = 15.8;
const float TIEMPO_PRUEBA_MS = 10000.0;

const float CM_POR_GRAMO = ALTURA_MAX_CM / GRAMOS_MAX;
const float MS_POR_CM_BAJAR = TIEMPO_PRUEBA_MS / CM_BAJADA_10S;
const float MS_POR_CM_SUBIR = TIEMPO_PRUEBA_MS / CM_SUBIDA_10S;
const float MS_POR_GRAMO_BAJAR = CM_POR_GRAMO * MS_POR_CM_BAJAR;
const float MS_POR_GRAMO_SUBIR = CM_POR_GRAMO * MS_POR_CM_SUBIR;

// La posición física DEBE comenzar en 0 g; no hay sensor de referencia.
float gramos = 0;

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

  // Validación adicional de la trama serial.
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

  if (nuevos_gramos != gramos) {
    // FASE 1: bajar hasta la referencia inferior.
    if (gramos > 0) {
      unsigned long tiempoBajar = (unsigned long)(gramos * MS_POR_GRAMO_BAJAR);
      tiempoBajar = (unsigned long)(tiempoBajar * 1.05); // Margen original de 5%

      motor.write(VELOCIDAD_INVERSA);
      delay(tiempoBajar);
      motor.write(DETENIDO);
      delay(600);
    }

    gramos = nuevos_gramos;

    // FASE 2: subir a la nueva posición.
    if (gramos > 0) {
      unsigned long tiempoSubir = (unsigned long)(gramos * MS_POR_GRAMO_SUBIR);
      motor.write(VELOCIDAD);
      delay(tiempoSubir);
      motor.write(DETENIDO);
    }
  }

  // Confirmación de finalización del programa, no de posición física.
  Serial.print("LISTO:");
  Serial.println((int)nuevos_gramos);
}
