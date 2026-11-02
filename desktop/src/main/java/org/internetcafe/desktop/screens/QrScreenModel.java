package org.internetcafe.desktop.screens;

/**
 * Datos de maquetación de la pantalla QR (D-02): código del equipo, sala, conexión y cuenta
 * regresiva.
 */
public final class QrScreenModel {

  private static final String DEFAULT_QR_PAYLOAD = "https://app.invalid/s#preview";

  private String machineCode;
  private String labName;
  private ConnectionStatus connectionStatus;
  private MachineMode machineMode;
  private int remainingSeconds;
  private String qrPayload;

  public QrScreenModel(
      String machineCode, String labName, ConnectionStatus connectionStatus, int remainingSeconds) {
    this(machineCode, labName, connectionStatus, remainingSeconds, MachineMode.KIOSK);
  }

  public QrScreenModel(
      String machineCode,
      String labName,
      ConnectionStatus connectionStatus,
      int remainingSeconds,
      MachineMode machineMode) {
    this.machineCode = requireText(machineCode, "código del equipo");
    this.labName = requireText(labName, "sala");
    this.connectionStatus = requireStatus(connectionStatus);
    this.machineMode = machineMode == null ? MachineMode.KIOSK : machineMode;
    this.remainingSeconds = requireNonNegative(remainingSeconds);
    this.qrPayload = DEFAULT_QR_PAYLOAD;
  }

  public String machineCode() {
    return machineCode;
  }

  public String labName() {
    return labName;
  }

  public ConnectionStatus connectionStatus() {
    return connectionStatus;
  }

  public MachineMode machineMode() {
    return machineMode;
  }

  public int remainingSeconds() {
    return remainingSeconds;
  }

  public String qrPayload() {
    return qrPayload;
  }

  public String connectionLabel() {
    return connectionStatus.label();
  }

  public String connectionStyleClass() {
    return connectionStatus.styleClass();
  }

  public String countdownLabel() {
    if (remainingSeconds <= 0) {
      return "Actualizando código…";
    }
    return "Se actualiza en " + remainingSeconds + " s";
  }

  public boolean skipVisible() {
    return machineMode == MachineMode.PASSIVE;
  }

  public void setIdentity(String machineCode, String labName) {
    this.machineCode = requireText(machineCode, "código del equipo");
    this.labName = requireText(labName, "sala");
  }

  public void setConnectionStatus(ConnectionStatus connectionStatus) {
    this.connectionStatus = requireStatus(connectionStatus);
  }

  public void setMachineMode(MachineMode machineMode) {
    this.machineMode = machineMode == null ? MachineMode.KIOSK : machineMode;
  }

  public void setRemainingSeconds(int remainingSeconds) {
    this.remainingSeconds = requireNonNegative(remainingSeconds);
  }

  public void setQrPayload(String qrPayload) {
    this.qrPayload = requireText(qrPayload, "contenido del QR");
  }

  private static String requireText(String value, String field) {
    if (value == null || value.isBlank()) {
      throw new IllegalArgumentException("El " + field + " no puede estar vacío");
    }
    return value.trim();
  }

  private static ConnectionStatus requireStatus(ConnectionStatus status) {
    if (status == null) {
      throw new IllegalArgumentException("El estado de conexión es obligatorio");
    }
    return status;
  }

  private static int requireNonNegative(int value) {
    if (value < 0) {
      throw new IllegalArgumentException("Los segundos restantes no pueden ser negativos");
    }
    return value;
  }
}
