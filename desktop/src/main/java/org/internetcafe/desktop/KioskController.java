package org.internetcafe.desktop;

import java.time.Duration;
import java.util.function.Consumer;
import java.util.function.LongSupplier;
import org.internetcafe.desktop.qr.ConnectionMonitor;
import org.internetcafe.desktop.screens.MachineMode;

/** Coordinates kiosk locking with the machine mode, active session, and API availability. */
public final class KioskController {

  static final Duration FAIL_OPEN_AFTER = Duration.ofMinutes(3);

  private final Consumer<Boolean> lockWindow;
  private final Consumer<Boolean> showFailOpen;
  private final LongSupplier nanoTime;

  private MachineMode mode = MachineMode.KIOSK;
  private boolean sessionActive;
  private boolean locked;
  private boolean failOpen;
  private boolean connectionLost;
  private long connectionLostAtNanos;

  public KioskController(
      Consumer<Boolean> lockWindow, Consumer<Boolean> showFailOpen, LongSupplier nanoTime) {
    if (lockWindow == null || showFailOpen == null || nanoTime == null) {
      throw new IllegalArgumentException("Kiosk controller dependencies must not be null");
    }
    this.lockWindow = lockWindow;
    this.showFailOpen = showFailOpen;
    this.nanoTime = nanoTime;
    updateLock();
  }

  public boolean isLocked() {
    return locked;
  }

  public boolean isFailOpen() {
    return failOpen;
  }

  public void setMode(MachineMode mode) {
    if (mode == null) {
      throw new IllegalArgumentException("Machine mode must not be null");
    }
    if (this.mode == mode) {
      return;
    }
    this.mode = mode;
    if (mode == MachineMode.PASSIVE) {
      connectionLost = false;
      setFailOpen(false);
    }
    updateLock();
  }

  public void setSessionActive(boolean sessionActive) {
    if (this.sessionActive == sessionActive) {
      return;
    }
    this.sessionActive = sessionActive;
    updateLock();
  }

  public void onConnectionStatus(ConnectionMonitor.Status status) {
    if (status == null) {
      throw new IllegalArgumentException("Connection status must not be null");
    }
    if (status.phase() == ConnectionMonitor.Phase.RESTORED) {
      connectionLost = false;
      setFailOpen(false);
    } else if (mode == MachineMode.KIOSK && !connectionLost) {
      connectionLost = true;
      connectionLostAtNanos = nanoTime.getAsLong();
    }
    tick();
  }

  /** Advances the fail-open timer; called periodically while the desktop is running. */
  public void tick() {
    if (mode == MachineMode.KIOSK
        && !sessionActive
        && connectionLost
        && nanoTime.getAsLong() - connectionLostAtNanos >= FAIL_OPEN_AFTER.toNanos()) {
      setFailOpen(true);
    }
    updateLock();
  }

  private void setFailOpen(boolean failOpen) {
    if (this.failOpen == failOpen) {
      return;
    }
    this.failOpen = failOpen;
    showFailOpen.accept(failOpen);
  }

  private void updateLock() {
    boolean shouldLock = mode == MachineMode.KIOSK && !sessionActive && !failOpen;
    if (locked == shouldLock) {
      return;
    }
    locked = shouldLock;
    lockWindow.accept(shouldLock);
  }
}
