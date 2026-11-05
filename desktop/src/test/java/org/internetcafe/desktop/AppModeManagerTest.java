package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.*;

import java.util.ArrayList;
import java.util.List;
import org.internetcafe.desktop.screens.MachineMode;
import org.junit.jupiter.api.Test;

class AppModeManagerTest {

  @Test
  void initialModeIsReturnedBeforeAnyHeartbeat() {
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, mode -> {});
    assertEquals(MachineMode.KIOSK, mgr.currentMode());
  }

  @Test
  void defaultsToKioskWhenInitialModeIsNull() {
    AppModeManager mgr = new AppModeManager(null, mode -> {});
    assertEquals(MachineMode.KIOSK, mgr.currentMode());
  }

  @Test
  void callbackInvokedOnModeChange() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyMode(MachineMode.PASSIVE);

    assertEquals(List.of(MachineMode.PASSIVE), received);
    assertEquals(MachineMode.PASSIVE, mgr.currentMode());
  }

  @Test
  void callbackNotInvokedWhenModeUnchanged() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyMode(MachineMode.KIOSK);

    assertTrue(received.isEmpty(), "No callback expected when mode stays the same");
  }

  @Test
  void nullModeIsIgnored() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyMode(null);

    assertTrue(received.isEmpty());
    assertEquals(MachineMode.KIOSK, mgr.currentMode());
  }

  @Test
  void applyModeFromStringParsesKiosk() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.PASSIVE, received::add);

    mgr.applyModeFromString("kiosk");

    assertEquals(List.of(MachineMode.KIOSK), received);
  }

  @Test
  void applyModeFromStringParsesPassiveCaseInsensitive() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyModeFromString("PASSIVE");

    assertEquals(List.of(MachineMode.PASSIVE), received);
  }

  @Test
  void applyModeFromStringIgnoresUnknownValue() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyModeFromString("turbo");

    assertTrue(received.isEmpty());
    assertEquals(MachineMode.KIOSK, mgr.currentMode());
  }

  @Test
  void applyModeFromStringIgnoresBlank() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyModeFromString("   ");

    assertTrue(received.isEmpty());
  }

  @Test
  void callbackExceptionDoesNotPropagateToCallers() {
    AppModeManager mgr =
        new AppModeManager(
            MachineMode.KIOSK,
            mode -> {
              throw new RuntimeException("simulated UI error");
            });

    assertDoesNotThrow(() -> mgr.applyMode(MachineMode.PASSIVE));
    assertEquals(MachineMode.PASSIVE, mgr.currentMode());
  }

  @Test
  void constructorRejectsNullCallback() {
    assertThrows(IllegalArgumentException.class, () -> new AppModeManager(MachineMode.KIOSK, null));
  }

  @Test
  void multipleModeTransitionsAreTrackedCorrectly() {
    List<MachineMode> received = new ArrayList<>();
    AppModeManager mgr = new AppModeManager(MachineMode.KIOSK, received::add);

    mgr.applyMode(MachineMode.PASSIVE);
    mgr.applyMode(MachineMode.PASSIVE); // same — no callback
    mgr.applyMode(MachineMode.KIOSK);

    assertEquals(List.of(MachineMode.PASSIVE, MachineMode.KIOSK), received);
  }
}
