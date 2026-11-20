#include <Servo.h>

// ==========================================================
// ARDUINO DE LOS VASOS (servo de rotacion continua, sin sensores)
// ----------------------------------------------------------
// Hay 4 vasos a la MISMA distancia entre si. El mecanismo se
// mueve DE A UN VASO: avanza de un centro al siguiente, se detiene,
// espera un momento, avanza al siguiente centro, y asi hasta llegar.
// Asi solo hay que calibrar cuanto tarda en ir de centro a centro
// hacia cada lado (MS_CENTRO_A_CENTRO_DERECHA / _IZQUIERDA).
//
// IMPORTANTE: al encender, dejar fisicamente el vaso de
// POSICION_INICIAL (Short) bajo el mecanismo de azucar.
// ==========================================================

Servo motorVasos;

const int PIN_MOTOR = 5;
const int DETENIDO = 91;            // Ajustar si tu servo no se detiene en 91.
const int VELOCIDAD_DERECHA = 130;
const int VELOCIDAD_IZQUIERDA = 55;

// ---------------- CALIBRACION ----------------
// Tiempo que tarda en pasar del CENTRO de un vaso al CENTRO del vecino.
// VALORES DE EJEMPLO: medirlos con los comandos "+" y "-" (ver abajo).
const unsigned long MS_CENTRO_A_CENTRO_DERECHA = 995;
const unsigned long MS_CENTRO_A_CENTRO_IZQUIERDA = 995;
// Pausa en cada centro para que el vaso se estabilice antes de seguir.
const unsigned long PAUSA_EN_CADA_VASO_MS = 800;

// Vasos fisicos, de izquierda a derecha:
//   0 = Short, 1 = Tall, 2 = Grande, 3 = Venti
// Solo y Doppio (espresso) no tienen vaso propio: usan el vaso Short.
const int NUM_VASOS = 4;
const int POSICION_INICIAL = 0;     // Short
int posicionActual = POSICION_INICIAL;

int posicionDelTamano(String tamano) {
  if (tamano == "Solo")   return 0;
  if (tamano == "Doppio") return 0;
  if (tamano == "Short")  return 0;
  if (tamano == "Tall")   return 1;
  if (tamano == "Grande") return 2;
  if (tamano == "Venti")  return 3;
  return -1;
}

// Mueve exactamente UN vaso hacia la derecha (+1) o izquierda (-1) y se detiene.
void moverUnVaso(int direccion) {
  if (direccion > 0) {
    motorVasos.write(VELOCIDAD_DERECHA);
    delay(MS_CENTRO_A_CENTRO_DERECHA);
  } else {
    motorVasos.write(VELOCIDAD_IZQUIERDA);
    delay(MS_CENTRO_A_CENTRO_IZQUIERDA);
  }
  motorVasos.write(DETENIDO);
  delay(PAUSA_EN_CADA_VASO_MS);
  // Actualiza la referencia LOGICA (no hay sensor que mida la posicion real).
  posicionActual += direccion;
}

void setup() {
  Serial.begin(9600);
  Serial.setTimeout(60);
  motorVasos.attach(PIN_MOTOR);
  motorVasos.write(DETENIDO);
}

void loop() {
  if (Serial.available() <= 0) return;

  String mensaje = Serial.readStringUntil('\n');
  mensaje.trim();
  if (mensaje.length() == 0) return;

  // ---- Comandos de prueba / calibracion (pagina o Monitor Serie) ----
  // "+" avanza un vaso a la derecha, "-" un vaso a la izquierda,
  // "?" informa la posicion logica actual, "DER:ms"/"IZQ:ms" giro manual,
  // "AQUI:<tamano>" fija la posicion sin moverse.
  // "+" / "-": avanza UN vaso (centro a centro) para probar, SIN revisar
  // limites y SIN cambiar la posicion que recuerda el Arduino.
  // Se puede apretar muchas veces seguidas sin tener que devolverlo.
  // Al terminar, deja un vaso centrado y usa "AQUI:<tamano>".
  if (mensaje == "+" || mensaje == "-") {
    int dir = (mensaje == "+") ? 1 : -1;
    moverUnVaso(dir);
    posicionActual -= dir;   // deshace el cambio de moverUnVaso: la posicion no cambia
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  if (mensaje == "?") {
    Serial.print("POS:");
    Serial.println(posicionActual);
    return;
  }

  // "DER:<ms>" / "IZQ:<ms>": gira ese tiempo exacto SIN cambiar la posicion
  // logica. Sirve para medir cuanto tarda de centro a centro.
  // Despues de usarlo, deja el vaso centrado y usa "AQUI:<tamano>".
  if (mensaje.startsWith("DER:") || mensaje.startsWith("IZQ:")) {
    unsigned long ms = mensaje.substring(4).toInt();
    if (ms > 20000) {
      Serial.println("ERROR:Maximo 20000 ms");
      return;
    }
    motorVasos.write(mensaje.startsWith("DER:") ? VELOCIDAD_DERECHA : VELOCIDAD_IZQUIERDA);
    delay(ms);
    motorVasos.write(DETENIDO);
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  // "AQUI:<tamano>": no se mueve, solo le dice al Arduino en que vaso esta.
  if (mensaje.startsWith("AQUI:")) {
    int pos = posicionDelTamano(mensaje.substring(5));
    if (pos == -1) {
      Serial.println("ERROR:Tamano no reconocido");
      return;
    }
    posicionActual = pos;
    Serial.print("LISTO:");
    Serial.println(mensaje);
    return;
  }

  // ---- Comando normal: nombre del tamano ----
  int destino = posicionDelTamano(mensaje);
  if (destino == -1) {
    Serial.println("ERROR:Tamano no reconocido");
    return;
  }

  // Avanza de a un vaso, deteniendose en cada centro, hasta llegar.
  while (posicionActual != destino) {
    moverUnVaso(destino > posicionActual ? 1 : -1);
  }

  Serial.print("LISTO:");
  Serial.println(mensaje);
}
