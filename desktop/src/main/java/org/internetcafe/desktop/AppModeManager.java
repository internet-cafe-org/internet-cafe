package org.internetcafe.desktop;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;
import java.util.logging.Logger;
import org.internetcafe.desktop.screens.MachineMode;

/**
 * Monitors the machine mode reported by the backend heartbeat and applies it in real time.
 *
 * <p>When the mode changes the registered {@link Consumer} is called on the thread that invoked
 * {@link #applyMode(MachineMode)}; callers must hop to the JavaFX thread themselves when updating
 * the UI.
 *
 * <p>Thread-safe: mode updates may arrive on any background thread.
 */
public final class AppModeManager {

  private static final Logger log = Logger.getLogger(AppModeManager.class.getName());

  private final AtomicReference<MachineMode> currentMode;
  private final Consumer<MachineMode> onModeChanged;
  private final AtomicBoolean started = new AtomicBoolean(false);

  /**
   * Creates a new manager with the given initial mode.
   *
   * @param initialMode the mode to use before the first heartbeat arrives
   * @param onModeChanged callback invoked whenever the mode changes; must not be {@code null}
   */
  public AppModeManager(MachineMode initialMode, Consumer<MachineMode> onModeChanged) {
    if (onModeChanged == null) {
      throw new IllegalArgumentException("onModeChanged must not be null");
    }
    this.currentMode =
        new AtomicReference<>(initialMode != null ? initialMode : MachineMode.KIOSK);
    this.onModeChanged = onModeChanged;
  }

  /** Returns the mode that is currently active. */
  public MachineMode currentMode() {
    return currentMode.get();
  }

  /**
   * Applies a mode update that arrived from the heartbeat. If the mode is the same as the current
   * one, the callback is <em>not</em> invoked. If {@code mode} is {@code null} the call is ignored.
   *
   * @param mode the mode reported by the latest heartbeat
   */
  public void applyMode(MachineMode mode) {
    if (mode == null) {
      log.warning("Received null machine mode from heartbeat — ignoring");
      return;
    }

    MachineMode previous = currentMode.getAndSet(mode);
    if (previous == mode) {
      return;
    }

    log.info("Machine mode changed: " + previous + " → " + mode);
    try {
      onModeChanged.accept(mode);
    } catch (RuntimeException e) {
      log.warning("Mode-change callback threw an exception: " + e.getMessage());
    }
  }

  /**
   * Convenience helper: parses the raw string value that comes in the heartbeat JSON and delegates
   * to {@link #applyMode(MachineMode)}.
   *
   * <p>Recognised values (case-insensitive): {@code "kiosk"}, {@code "passive"}. Unrecognised
   * values are logged and ignored.
   *
   * @param raw the string value from the heartbeat, e.g. {@code "passive"}
   */
  public void applyModeFromString(String raw) {
    if (raw == null || raw.isBlank()) {
      log.warning("Received blank machine mode string from heartbeat — ignoring");
      return;
    }
    MachineMode mode;
    try {
      mode = MachineMode.valueOf(raw.trim().toUpperCase());
    } catch (IllegalArgumentException e) {
      log.warning("Unknown machine mode value from heartbeat: \"" + raw + "\" — ignoring");
      return;
    }
    applyMode(mode);
  }
}
