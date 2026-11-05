package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.internetcafe.desktop.qr.ConnectionMonitor;
import org.internetcafe.desktop.screens.MachineMode;
import org.junit.jupiter.api.Test;

class KioskControllerTest {

  private final AtomicLong nanoTime = new AtomicLong();
  private final List<Boolean> lockChanges = new ArrayList<>();
  private final List<Boolean> failOpenChanges = new ArrayList<>();

  private KioskController controller() {
    return new KioskController(lockChanges::add, failOpenChanges::add, nanoTime::get);
  }

  @Test
  void locksByDefaultAndUnlocksDuringAnActiveSessionThenLocksAgain() {
    KioskController controller = controller();

    assertTrue(controller.isLocked());
    controller.setSessionActive(true);
    assertFalse(controller.isLocked());
    controller.setSessionActive(false);
    assertTrue(controller.isLocked());
    assertEquals(List.of(true, false, true), lockChanges);
  }

  @Test
  void passiveModeUnlocksAndReturningToKioskRelocks() {
    KioskController controller = controller();

    controller.setMode(MachineMode.PASSIVE);
    assertFalse(controller.isLocked());
    controller.setMode(MachineMode.KIOSK);
    assertTrue(controller.isLocked());
    assertEquals(List.of(true, false, true), lockChanges);
  }

  @Test
  void remainsLockedUntilApiHasBeenUnavailableForThreeMinutesThenRelocksOnRecovery() {
    KioskController controller = controller();
    controller.onConnectionStatus(status(ConnectionMonitor.Phase.CONNECTING));

    advance(Duration.ofMinutes(2).plusSeconds(59));
    controller.tick();
    assertTrue(controller.isLocked());
    assertFalse(controller.isFailOpen());

    advance(Duration.ofSeconds(1));
    controller.tick();
    assertFalse(controller.isLocked());
    assertTrue(controller.isFailOpen());
    assertEquals(List.of(true, false), lockChanges);
    assertEquals(List.of(true), failOpenChanges);

    controller.onConnectionStatus(status(ConnectionMonitor.Phase.RESTORED));
    assertTrue(controller.isLocked());
    assertFalse(controller.isFailOpen());
    assertEquals(List.of(true, false, true), lockChanges);
    assertEquals(List.of(true, false), failOpenChanges);
  }

  @Test
  void connectionRecoveryBeforeThreeMinutesKeepsKioskLocked() {
    KioskController controller = controller();
    controller.onConnectionStatus(status(ConnectionMonitor.Phase.RETRYING));
    advance(Duration.ofMinutes(2));

    controller.onConnectionStatus(status(ConnectionMonitor.Phase.RESTORED));
    controller.tick();

    assertTrue(controller.isLocked());
    assertFalse(controller.isFailOpen());
    assertEquals(List.of(true), lockChanges);
    assertTrue(failOpenChanges.isEmpty());
  }

  @Test
  void activeSessionDoesNotEnterFailOpenButDoesWhenSessionEndsOffline() {
    KioskController controller = controller();
    controller.setSessionActive(true);
    controller.onConnectionStatus(status(ConnectionMonitor.Phase.CONNECTING));
    advance(Duration.ofMinutes(3));

    controller.tick();
    assertFalse(controller.isLocked());
    assertFalse(controller.isFailOpen());
    assertTrue(failOpenChanges.isEmpty());

    controller.setSessionActive(false);
    controller.tick();
    assertFalse(controller.isLocked());
    assertTrue(controller.isFailOpen());
    assertEquals(List.of(true), failOpenChanges);
  }

  @Test
  void leavingFailOpenClearsTheTimerAndKioskModeLocksAgain() {
    KioskController controller = controller();
    controller.onConnectionStatus(status(ConnectionMonitor.Phase.CONNECTING));
    advance(Duration.ofMinutes(3));
    controller.tick();
    assertTrue(controller.isFailOpen());
    assertFalse(controller.isLocked());

    controller.setMode(MachineMode.PASSIVE);
    assertFalse(controller.isFailOpen());
    assertFalse(controller.isLocked());
    controller.setMode(MachineMode.KIOSK);

    assertTrue(controller.isLocked());
    assertFalse(controller.isFailOpen());
  }

  private static ConnectionMonitor.Status status(ConnectionMonitor.Phase phase) {
    return new ConnectionMonitor.Status(phase, 1, 0L);
  }

  private void advance(Duration duration) {
    nanoTime.addAndGet(duration.toNanos());
  }
}
