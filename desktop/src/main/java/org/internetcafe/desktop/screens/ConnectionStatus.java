package org.internetcafe.desktop.screens;

/** Estado de conexión con la API, visible en la pantalla QR (RF-EQU-06). */
public enum ConnectionStatus {
  ONLINE("En línea", "online"),
  CONNECTING("Conectando…", "connecting"),
  OFFLINE("Sin conexión", "offline");

  private final String label;
  private final String styleClass;

  ConnectionStatus(String label, String styleClass) {
    this.label = label;
    this.styleClass = styleClass;
  }

  public String label() {
    return label;
  }

  public String styleClass() {
    return styleClass;
  }
}
