package org.internetcafe.desktop.screens;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.internetcafe.desktop.qr.ConnectionMonitor.Phase;
import org.internetcafe.desktop.qr.ConnectionMonitor.Status;
import org.junit.jupiter.api.Test;

class OfflineScreenModelTest {

  @Test
  void connectingShowsADisabledButton() {
    OfflineScreenModel model = OfflineScreenModel.from(new Status(Phase.CONNECTING, 0, 0L));

    assertEquals("Conectando…", model.title());
    assertTrue(model.retryVisible());
    assertFalse(model.retryEnabled());
    assertEquals("Deshabilitado", model.retryLabel());
    assertFalse(model.homeVisible());
  }

  @Test
  void retryingShowsTheCountdownAndTheIntervals() {
    OfflineScreenModel model = OfflineScreenModel.from(new Status(Phase.RETRYING, 2, 4L));

    assertEquals("Reintentando conexión…", model.title());
    assertEquals("Próximo intento en 4 s (intervalos: 2s, 4s, 8s, máx 30s)", model.detail());
    assertFalse(model.retryVisible());
    assertEquals(OfflineScreenModel.Tone.INFO, model.tone());
  }

  @Test
  void prolongedFailureOffersManualRetryAndGoingHome() {
    OfflineScreenModel model = OfflineScreenModel.from(new Status(Phase.PROLONGED, 5, 30L));

    assertEquals("Fallo prolongado", model.title());
    assertEquals("Contacta al soporte técnico", model.bannerTitle());
    assertEquals(OfflineScreenModel.Tone.WARNING, model.tone());
    assertTrue(model.retryVisible());
    assertTrue(model.retryEnabled());
    assertEquals("Reintentar conexión", model.retryLabel());
    assertTrue(model.homeVisible());
    assertTrue(model.detail().contains("30 s"));
  }

  @Test
  void prolongedFailureWhileCheckingHasNoCountdown() {
    OfflineScreenModel model = OfflineScreenModel.from(new Status(Phase.PROLONGED, 5, 0L));

    assertFalse(model.detail().contains("Próximo intento"));
  }

  @Test
  void restoredShowsTheSuccessMessage() {
    OfflineScreenModel model = OfflineScreenModel.from(new Status(Phase.RESTORED, 0, 0L));

    assertEquals("Conexión restablecida", model.title());
    assertEquals("Comunicación con el servidor recuperada", model.subtitle());
    assertEquals(OfflineScreenModel.Tone.SUCCESS, model.tone());
    assertFalse(model.retryVisible());
    assertFalse(model.homeVisible());
  }
}
