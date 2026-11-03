package org.internetcafe.desktop.screens;

import org.internetcafe.desktop.qr.ConnectionMonitor;

/** Texts and visible parts of the offline screen (DSK-09) for each connection phase. */
public record OfflineScreenModel(
    String icon,
    String title,
    String subtitle,
    String detail,
    Tone tone,
    String bannerTitle,
    String bannerText,
    boolean retryVisible,
    boolean retryEnabled,
    String retryLabel,
    boolean homeVisible) {

  /** Color family of the icon and the banner. */
  public enum Tone {
    INFO("tone-info"),
    WARNING("tone-warning"),
    SUCCESS("tone-success");

    private final String styleClass;

    Tone(String styleClass) {
      this.styleClass = styleClass;
    }

    public String styleClass() {
      return styleClass;
    }
  }

  private static final String AUTO_RETRY =
      "El sistema intentará restablecer la conexión automáticamente.";

  public static OfflineScreenModel from(ConnectionMonitor.Status status) {
    long next = status.nextAttemptInSeconds();
    return switch (status.phase()) {
      case CONNECTING ->
          new OfflineScreenModel(
              "⟳",
              "Conectando…",
              AUTO_RETRY,
              "",
              Tone.INFO,
              "",
              "",
              true,
              false,
              "Deshabilitado",
              false);
      case RETRYING ->
          new OfflineScreenModel(
              "⟳",
              "Reintentando conexión…",
              AUTO_RETRY,
              "Próximo intento en " + next + " s (intervalos: 2s, 4s, 8s, máx 30s)",
              Tone.INFO,
              "",
              "",
              false,
              false,
              "",
              false);
      case PROLONGED ->
          new OfflineScreenModel(
              "⚠",
              "Fallo prolongado",
              "No se pudo establecer comunicación con el servidor API",
              next > 0 ? AUTO_RETRY + " Próximo intento en " + next + " s." : AUTO_RETRY,
              Tone.WARNING,
              "Contacta al soporte técnico",
              "Algunas funciones podrían no estar disponibles mientras se restablezca la conexión",
              true,
              true,
              "Reintentar conexión",
              true);
      case RESTORED ->
          new OfflineScreenModel(
              "✓",
              "Conexión restablecida",
              "Comunicación con el servidor recuperada",
              "",
              Tone.SUCCESS,
              "Conexión restablecida",
              "",
              false,
              false,
              "",
              false);
    };
  }
}
