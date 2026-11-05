package org.internetcafe.desktop;

import java.util.concurrent.atomic.AtomicBoolean;
import org.internetcafe.desktop.screens.MachineMode;

/**
 * Coordinates the passive mode: "skip" stops the QR codes and sends the app to the tray, and
 * "register access" brings the app back and restarts the QR codes.
 *
 * <p>Every action is injected, so the logic can be tested without JavaFX. Calls are idempotent:
 * entering passive mode twice (or resuming while active) does nothing. Invoke it from the JavaFX
 * thread, because the actions touch the UI.
 */
public final class PassiveModeController {

  private final Runnable stopQr;
  private final Runnable startQr;
  private final Runnable showPassiveUi;
  private final Runnable hidePassiveUi;
  private final AtomicBoolean passive = new AtomicBoolean(false);

  public PassiveModeController(
      Runnable stopQr, Runnable startQr, Runnable showPassiveUi, Runnable hidePassiveUi) {
    if (stopQr == null || startQr == null || showPassiveUi == null || hidePassiveUi == null) {
      throw new IllegalArgumentException("Passive mode actions must not be null");
    }
    this.stopQr = stopQr;
    this.startQr = startQr;
    this.showPassiveUi = showPassiveUi;
    this.hidePassiveUi = hidePassiveUi;
  }

  /** Returns {@code true} while the machine is in passive mode. */
  public boolean isPassive() {
    return passive.get();
  }

  /** Stops the QR codes and shows the passive UI. Returns {@code false} if already passive. */
  public boolean enterPassive() {
    if (!passive.compareAndSet(false, true)) {
      return false;
    }
    stopQr.run();
    showPassiveUi.run();
    return true;
  }

  /** Hides the passive UI and restarts the QR codes. Returns {@code false} if not passive. */
  public boolean resume() {
    if (!passive.compareAndSet(true, false)) {
      return false;
    }
    hidePassiveUi.run();
    startQr.run();
    return true;
  }

  /** Maps a machine mode to the matching transition; unknown modes are ignored. */
  public void applyMode(MachineMode mode) {
    if (mode == MachineMode.PASSIVE) {
      enterPassive();
    } else if (mode == MachineMode.KIOSK) {
      resume();
    }
  }
}