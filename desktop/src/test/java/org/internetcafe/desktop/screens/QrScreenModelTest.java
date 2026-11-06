package org.internetcafe.desktop.screens;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class QrScreenModelTest {

  @Test
  void showsMachineCodeLabAndConnectionFromWireframe() {
    QrScreenModel model = new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 45);

    assertEquals("LAB1-PC03", model.machineCode());
    assertEquals("Sala 1", model.labName());
    assertEquals("En línea", model.connectionLabel());
    assertEquals("online", model.connectionStyleClass());
    assertEquals("Se actualiza en 45 s", model.countdownLabel());
    assertFalse(model.skipVisible());
  }

  @Test
  void connectingAndOfflineUseTheExpectedLabels() {
    QrScreenModel connecting =
        new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.CONNECTING, 12);
    QrScreenModel offline = new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.OFFLINE, 0);

    assertEquals("Conectando…", connecting.connectionLabel());
    assertEquals("connecting", connecting.connectionStyleClass());
    assertEquals("Sin conexión", offline.connectionLabel());
    assertEquals("Actualizando código…", offline.countdownLabel());
  }

  @Test
  void skipIsVisibleOnlyInPassiveMode() {
    QrScreenModel model =
        new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 30, MachineMode.PASSIVE);

    assertTrue(model.skipVisible());
    model.setMachineMode(MachineMode.KIOSK);
    assertFalse(model.skipVisible());
  }

  @Test
  void rejectsBlankIdentity() {
    assertThrows(
        IllegalArgumentException.class,
        () -> new QrScreenModel("  ", "Sala 1", ConnectionStatus.ONLINE, 10));
    assertThrows(
        IllegalArgumentException.class,
        () -> new QrScreenModel("LAB1-PC03", "", ConnectionStatus.ONLINE, 10));
  }
}
