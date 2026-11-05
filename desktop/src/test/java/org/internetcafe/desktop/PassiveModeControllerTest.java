package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.*;

import java.util.ArrayList;
import java.util.List;
import org.internetcafe.desktop.screens.MachineMode;
import org.junit.jupiter.api.Test;

class PassiveModeControllerTest {

  private final List<String> events = new ArrayList<>();

  private PassiveModeController controller() {
    return new PassiveModeController(
        () -> events.add("stopQr"),
        () -> events.add("startQr"),
        () -> events.add("showUi"),
        () -> events.add("hideUi"));
  }

  @Test
  void startsActive() {
    assertFalse(controller().isPassive());
  }

  @Test
  void enterPassiveStopsQrThenShowsPassiveUi() {
    PassiveModeController controller = controller();

    assertTrue(controller.enterPassive());

    assertTrue(controller.isPassive());
    assertEquals(List.of("stopQr", "showUi"), events);
  }

  @Test
  void resumeHidesPassiveUiThenRestartsQr() {
    PassiveModeController controller = controller();
    controller.enterPassive();
    events.clear();

    assertTrue(controller.resume());

    assertFalse(controller.isPassive());
    assertEquals(List.of("hideUi", "startQr"), events);
  }

  @Test
  void enteringPassiveTwiceRunsTheActionsOnlyOnce() {
    PassiveModeController controller = controller();

    assertTrue(controller.enterPassive());
    assertFalse(controller.enterPassive());

    assertEquals(List.of("stopQr", "showUi"), events);
  }

  @Test
  void resumingWhileActiveDoesNothing() {
    PassiveModeController controller = controller();

    assertFalse(controller.resume());

    assertTrue(events.isEmpty());
  }

  @Test
  void applyModeMapsPassiveAndKiosk() {
    PassiveModeController controller = controller();

    controller.applyMode(MachineMode.PASSIVE);
    assertTrue(controller.isPassive());

    controller.applyMode(MachineMode.KIOSK);
    assertFalse(controller.isPassive());

    assertEquals(List.of("stopQr", "showUi", "hideUi", "startQr"), events);
  }

  @Test
  void applyModeIgnoresNull() {
    PassiveModeController controller = controller();

    controller.applyMode(null);

    assertFalse(controller.isPassive());
    assertTrue(events.isEmpty());
  }

  @Test
  void constructorRejectsNullActions() {
    Runnable noop = () -> {};
    assertThrows(
        IllegalArgumentException.class, () -> new PassiveModeController(null, noop, noop, noop));
    assertThrows(
        IllegalArgumentException.class, () -> new PassiveModeController(noop, noop, noop, null));
  }
}