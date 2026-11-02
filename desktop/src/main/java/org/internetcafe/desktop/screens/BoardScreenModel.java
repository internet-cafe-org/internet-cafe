package org.internetcafe.desktop.screens;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/**
 * Datos del tablero b\u00e1sico (DSK-06): nombre, c\u00f3digo enmascarado, hora de inicio y
 * cron\u00f3metro. Es l\u00f3gica pura, sin JavaFX, para poder probarla con JUnit.
 */
public final class BoardScreenModel {

  private static final String MASK = "****";
  private static final int VISIBLE_CODE_CHARS = 2;
  private static final int MIN_LENGTH_TO_SHOW_SUFFIX = 5;
  private static final DateTimeFormatter TIME_FORMAT = DateTimeFormatter.ofPattern("HH:mm:ss");

  private final String userName;
  private final String code;
  private final Instant startedAt;
  private final Clock clock;

  public BoardScreenModel(String userName, String code, Instant startedAt, Clock clock) {
    this.userName = requireText(userName, "nombre");
    this.code = requireText(code, "c\u00f3digo");
    if (startedAt == null || clock == null) {
      throw new IllegalArgumentException("La hora de inicio y el reloj son obligatorios");
    }
    this.startedAt = startedAt;
    this.clock = clock;
  }

  public String userName() {
    return userName;
  }

  public Instant startedAt() {
    return startedAt;
  }

  /**
   * C\u00f3digo con todo oculto salvo los dos \u00faltimos caracteres (si es lo bastante largo).
   */
  public String maskedCode() {
    if (code.length() < MIN_LENGTH_TO_SHOW_SUFFIX) {
      return MASK;
    }
    return MASK + code.substring(code.length() - VISIBLE_CODE_CHARS);
  }

  public String startTimeLabel() {
    return TIME_FORMAT.withZone(clock.getZone()).format(startedAt);
  }

  /** Tiempo transcurrido desde el inicio, nunca negativo. */
  public Duration elapsed() {
    Duration elapsed = Duration.between(startedAt, clock.instant());
    return elapsed.isNegative() ? Duration.ZERO : elapsed;
  }

  public String elapsedLabel() {
    Duration elapsed = elapsed();
    return String.format(
        Locale.ROOT,
        "%02d:%02d:%02d",
        elapsed.toHours(),
        elapsed.toMinutesPart(),
        elapsed.toSecondsPart());
  }

  private static String requireText(String value, String field) {
    if (value == null || value.isBlank()) {
      throw new IllegalArgumentException("El " + field + " no puede estar vac\u00edo");
    }
    return value.trim();
  }
}
