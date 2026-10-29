package org.internetcafe.desktop.qr;

import java.util.function.LongSupplier;

/** Cuenta regresiva para la rotación del QR, medida con {@link System#nanoTime()}. */
public final class QrCountdown {

  private static final long NANOS_PER_SECOND = 1_000_000_000L;

  private final long durationNanos;
  private final LongSupplier clock;
  private long startNanos;

  /**
   * Crea la cuenta regresiva y la inicia de inmediato.
   *
   * @param rotateAfterSeconds segundos de vida del QR (valor {@code rotate_after_s})
   */
  public QrCountdown(int rotateAfterSeconds) {
    this(rotateAfterSeconds, System::nanoTime);
  }

  /** Constructor para pruebas: permite inyectar un reloj falso. */
  QrCountdown(int rotateAfterSeconds, LongSupplier clock) {
    if (rotateAfterSeconds <= 0) {
      throw new IllegalArgumentException("rotate_after_s debe ser mayor que cero");
    }
    this.durationNanos = rotateAfterSeconds * NANOS_PER_SECOND;
    this.clock = clock;
    this.startNanos = clock.getAsLong();
  }

  /** Reinicia la cuenta desde el valor completo. */
  public void restart() {
    startNanos = clock.getAsLong();
  }

  /** Nanosegundos que faltan (nunca negativo). */
  public long remainingNanos() {
    long elapsed = clock.getAsLong() - startNanos;
    return Math.max(0L, durationNanos - elapsed);
  }

  /** Segundos que faltan, redondeados hacia arriba (para mostrar en pantalla). */
  public int remainingSeconds() {
    return (int) ((remainingNanos() + NANOS_PER_SECOND - 1) / NANOS_PER_SECOND);
  }

  /** Indica si el tiempo ya se acabó. */
  public boolean isExpired() {
    return remainingNanos() == 0L;
  }
}
