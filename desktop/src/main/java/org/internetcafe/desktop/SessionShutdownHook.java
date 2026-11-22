package org.internetcafe.desktop;

import java.io.IOException;
import java.util.function.BooleanSupplier;
import java.util.logging.Logger;

public final class SessionShutdownHook implements Runnable {
  private static final Logger log = Logger.getLogger(SessionShutdownHook.class.getName());

  @FunctionalInterface
  public interface SessionCloser {
    void close() throws IOException, InterruptedException;
  }

  private final BooleanSupplier hasActiveSession;
  private final SessionCloser sessionCloser;

  public SessionShutdownHook(BooleanSupplier hasActiveSession, SessionCloser sessionCloser) {
    if (hasActiveSession == null || sessionCloser == null) {
      throw new IllegalArgumentException("Shutdown hook dependencies must not be null");
    }
    this.hasActiveSession = hasActiveSession;
    this.sessionCloser = sessionCloser;
  }

  @Override
  public void run() {
    if (!hasActiveSession.getAsBoolean()) {
      return;
    }
    try {
      sessionCloser.close();
    } catch (InterruptedException exception) {
      Thread.currentThread().interrupt();
      log.warning("Shutdown session close interrupted");
    } catch (IOException | RuntimeException exception) {
      log.warning("Shutdown session close failed: " + exception.getClass().getSimpleName());
    }
  }
}
