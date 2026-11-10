#include <Servo.h>

// SEGUNDO ARDUINO LEONARDO: mueve un servo de ROTACION CONTINUA
// al tamano de vaso seleccionado (sin sensores de posicion).
// IMPORTANTE: poner el mecanismo fisicamente en Tall ANTES de arrancar.
Servo motorVasos;

const int PIN_MOTOR = 5;
const int DETENIDO = 90;          // Ajustar si tu servo no se detiene en 90.
const int VELOCIDAD_DERECHA = 110;
const int VELOCIDAD_IZQUIERDA = 75;

// VALOR DE EJEMPLO, NO CALIBRADO: mide cuanto tarda tu mecanismo
// en ir de una posicion a la siguiente sin llegar a topes mecanicos.
const unsigned long MS_POR_PASO_DERECHA = 450;
const unsigned long MS_POR_PASO_IZQUIERDA = 450;

// Posiciones logicas en el mecanismo, de izquierda a derecha:
// Solo(0), Doppio(1), Short(2), Tall(3), Grande(4), Venti(5)
// Se asume que al encender esta fisicamente en Tall.
int posicionActual = 3;

int posicionDelTamano(String tamano) {
  if (tamano == "Solo") return 0;
  if (tamano == "Doppio") return 1;
  if (tamano == "Short") return 2;
  if (tamano == "Tall") return 3;
  if (tamano == "Grande") return 4;
  if (tamano == "Venti") return 5;
  return -1;
}

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(60);
  motorVasos.attach(PIN_MOTOR);
  motorVasos.write(DETENIDO);
}

void loop() {
  if (Serial.available() <= 0) return;

  String tamano = Serial.readStringUntil('\n');
  tamano.trim();
  if (tamano.length() == 0) return;

  int destino = posicionDelTamano(tamano);
  if (destino == -1) {
    Serial.println("ERROR:Tamano no reconocido");
    return;
  }

  int pasos = destino - posicionActual;
  if (pasos != 0) {
    unsigned long msPorPaso = pasos > 0 ? MS_POR_PASO_DERECHA : MS_POR_PASO_IZQUIERDA;
    unsigned long duracion = (unsigned long)abs(pasos) * msPorPaso;
    motorVasos.write(pasos > 0 ? VELOCIDAD_DERECHA : VELOCIDAD_IZQUIERDA);
    delay(duracion);
    motorVasos.write(DETENIDO);
    // Actualiza la referencia LOGICA, no mide la posicion real.
    posicionActual = destino;
  }

  Serial.print("LISTO:");
  Serial.println(tamano);
}
