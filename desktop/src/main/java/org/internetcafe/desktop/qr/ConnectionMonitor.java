package org.internetcafe.desktop.qr;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

/**
 * Checks the API on a virtual thread after a network failure was reported, waiting 2, 4, 8... up to
 * 30 seconds between attempts, until the API answers again.
 *
 * <p>Phases: CONNECTING (checking), RETRYING (waiting for the next attempt), PROLONGED (the check
 * failed {@value #PROLONGED_AFTER_FAILURES} times or more; it keeps retrying) and RESTORED
 * (terminal; the API answered). The listener is called from the worker thread, so UI code must hop
 * to its own thread. Nothing from the responses is written to the log.
 */
public final class ConnectionMonitor implements AutoCloseable {

  public static final int PROLONGED_AFTER_FAILURES = 5;

  private static final long TICK_MILLIS = 1_000L;
  private static final Logger log = Logger.getLogger(ConnectionMonitor.class.getName());

  /** What the screen should show right now. */
  public enum Phase {
    CONNECTING,
    RETRYING,
    PROLONGED,
    RESTORED
  }

  /** Snapshot published to the listener; nextAttemptInSeconds is 0 while a check is running. */
  public record Status(Phase phase, int failedAttempts, long nextAttemptInSeconds) {}

  @FunctionalInterface
  public interface HealthCheck {
    void check() throws IOException, InterruptedException;
  }

  @FunctionalInterface
  public interface Listener {
    void onStatus(Status status);
  }

  /** Waits one second between countdown updates; replaced in tests. */
  @FunctionalInterface
  interface Ticker {
    void tick() throws InterruptedException;
  }

  private final HealthCheck healthCheck;
  private final Listener listener;
  private final Ticker ticker;
  private final AtomicBoolean active = new AtomicBoolean();
  private final AtomicBoolean retryRequested = new AtomicBoolean();
  private final AtomicInteger generation = new AtomicInteger();
  private volatile Thread worker;

  public ConnectionMonitor(HealthCheck healthCheck, Listener listener) {
    this(healthCheck, listener, () -> Thread.sleep(TICK_MILLIS));
  }

  ConnectionMonitor(HealthCheck healthCheck, Listener listener, Ticker ticker) {
    if (healthCheck == null || listener == null || ticker == null) {
      throw new IllegalArgumentException("Connection monitor dependencies must not be null");
    }
    this.healthCheck = healthCheck;
    this.listener = listener;
    this.ticker = ticker;
  }

  public boolean isActive() {
    return active.get();
  }

  /** Starts checking the API. Does nothing if a check cycle is already running. */
  public void reportFailure() {
    if (!active.compareAndSet(false, true)) {
      return;
    }
    int cycle = generation.get();
    log.info("Connection lost; checking the API with growing delays");
    Thread thread = Thread.ofVirtual().name("connection-monitor").unstarted(() -> run(cycle));
    worker = thread;
    thread.start();
  }

  /** Skips the current wait and checks the API right now (manual "Reintentar conexión"). */
  public void retryNow() {
    if (!active.get()) {
      reportFailure();
      return;
    }
    retryRequested.set(true);
    Thread thread = worker;
    if (thread != null) {
      thread.interrupt();
    }
  }

  /** Cancels the current cycle. A later reportFailure() starts a fresh one. */
  public void stop() {
    generation.incrementAndGet();
    active.set(false);
    retryRequested.set(false);
    Thread thread = worker;
    if (thread != null) {
      thread.interrupt();
    }
  }

  @Override
  public void close() {
    stop();
  }

  private boolean isCurrent(int cycle) {
    return active.get() && generation.get() == cycle;
  }

  private void run(int cycle) {
    ExponentialBackoff backoff = new ExponentialBackoff();
    retryRequested.set(false);
    int failures = 0;
    while (isCurrent(cycle)) {
      publish(cycle, new Status(probePhase(failures), failures, 0L));
      try {
        healthCheck.check();
      } catch (InterruptedException e) {
        if (retryRequested.getAndSet(false)) {
          Thread.interrupted();
          continue;
        }
        Thread.currentThread().interrupt();
        return;
      } catch (IOException | RuntimeException e) {
        failures++;
        Phase phase = failures >= PROLONGED_AFTER_FAILURES ? Phase.PROLONGED : Phase.RETRYING;
        if (!waitBeforeRetry(cycle, backoff.nextDelaySeconds(), phase, failures)) {
          return;
        }
        continue;
      }
      finish(cycle);
      return;
    }
  }

  private static Phase probePhase(int failures) {
    return failures >= PROLONGED_AFTER_FAILURES ? Phase.PROLONGED : Phase.CONNECTING;
  }

  /** Counts down second by second; returns false when the cycle was cancelled. */
  private boolean waitBeforeRetry(int cycle, long seconds, Phase phase, int failures) {
    for (long remaining = seconds; remaining > 0; remaining--) {
      if (!isCurrent(cycle)) {
        return false;
      }
      publish(cycle, new Status(phase, failures, remaining));
      try {
        ticker.tick();
      } catch (InterruptedException e) {
        if (retryRequested.getAndSet(false)) {
          Thread.interrupted();
          return true;
        }
        Thread.currentThread().interrupt();
        return false;
      }
      if (retryRequested.getAndSet(false)) {
        return true;
      }
    }
    return isCurrent(cycle);
  }

  private void finish(int cycle) {
    if (!isCurrent(cycle)) {
      return;
    }
    retryRequested.set(false);
    active.set(false);
    log.info("Connection restored");
    notifyListener(new Status(Phase.RESTORED, 0, 0L));
  }

  private void publish(int cycle, Status status) {
    if (isCurrent(cycle)) {
      notifyListener(status);
    }
  }

  private void notifyListener(Status status) {
    try {
      listener.onStatus(status);
    } catch (RuntimeException e) {
      log.warning("Connection status listener failed");
    }
  }
}
