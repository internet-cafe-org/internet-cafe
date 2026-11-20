package org.internetcafe.desktop.qr;

import java.io.IOException;
import java.time.Clock;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.logging.Logger;
import org.internetcafe.desktop.contract.HeartbeatResponse;

/**
 * Sends the machine heartbeat every 60 s, always (with or without a session), and detects a remote
 * close: when the server answers {@code ended} for the session the machine believes is open, the
 * close is logged and the listener is notified exactly once. With a 5 s request timeout the remote
 * close is noticed within 65 s (DSK-08).
 */
public final class HeartbeatService implements AutoCloseable {

  public static final int INTERVAL_SECONDS = 60;

  private static final Logger log = Logger.getLogger(HeartbeatService.class.getName());

  @FunctionalInterface
  public interface Sender {
    HeartbeatResponse send(String sessionId) throws IOException, InterruptedException;
  }

  @FunctionalInterface
  public interface RemoteCloseListener {
    void onRemoteClose(String sessionId, String endReason);
  }

  private final Sender sender;
  private final RemoteCloseListener listener;
  private final Clock clock;
  private final AtomicReference<String> sessionId = new AtomicReference<>();
  private ScheduledExecutorService executor;

  public HeartbeatService(Sender sender, RemoteCloseListener listener) {
    this(sender, listener, Clock.systemUTC());
  }

  HeartbeatService(Sender sender, RemoteCloseListener listener, Clock clock) {
    if (sender == null || listener == null || clock == null) {
      throw new IllegalArgumentException("Heartbeat dependencies must not be null");
    }
    this.sender = sender;
    this.listener = listener;
    this.clock = clock;
  }

  /** Sets the session the machine believes is open, or {@code null} when there is none. */
  public void setSessionId(String id) {
    sessionId.set(id == null || id.isBlank() ? null : id);
  }

  /** Starts the periodic heartbeat; the first one goes out immediately. */
  public synchronized void start() {
    if (executor != null) {
      return;
    }
    executor =
        Executors.newSingleThreadScheduledExecutor(
            runnable -> {
              Thread thread = new Thread(runnable, "heartbeat");
              thread.setDaemon(true);
              return thread;
            });
    executor.scheduleAtFixedRate(this::beat, 0L, INTERVAL_SECONDS, TimeUnit.SECONDS);
  }

  /** Stops the heartbeat. Safe to call more than once. */
  public synchronized void stop() {
    if (executor != null) {
      executor.shutdownNow();
      executor = null;
    }
  }

  @Override
  public void close() {
    stop();
  }

  void beat() {
    String sent = sessionId.get();
    try {
      HeartbeatResponse response = sender.send(sent);
      if (sent != null
          && response != null
          && response.ended()
          && sessionId.compareAndSet(sent, null)) {
        log.info(
            "Cierre remoto detectado: sesion="
                + sent
                + ", motivo="
                + response.endReason()
                + ", a las "
                + clock.instant());
        listener.onRemoteClose(sent, response.endReason());
      }
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    } catch (IOException | RuntimeException e) {
      log.warning("Latido fallido: " + e.getClass().getSimpleName());
    }
  }
}
