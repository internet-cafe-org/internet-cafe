package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Handler;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import org.junit.jupiter.api.Test;

class SessionShutdownHookTest {
  @Test
  void closesTheSessionWhenOneIsActive() {
    AtomicInteger closeCalls = new AtomicInteger();
    SessionShutdownHook hook = new SessionShutdownHook(() -> true, closeCalls::incrementAndGet);

    hook.run();

    assertEquals(1, closeCalls.get());
  }

  @Test
  void doesNotCallTheServerWhenThereIsNoActiveSession() {
    AtomicInteger closeCalls = new AtomicInteger();
    SessionShutdownHook hook = new SessionShutdownHook(() -> false, closeCalls::incrementAndGet);

    hook.run();

    assertEquals(0, closeCalls.get());
  }

  @Test
  void closeFailureDoesNotPreventJvmShutdown() {
    SessionShutdownHook hook =
        new SessionShutdownHook(
            () -> true,
            () -> {
              throw new IOException("private-session-placeholder");
            });

    assertDoesNotThrow(hook::run);
  }

  @Test
  void unexpectedFailureDoesNotPreventJvmShutdown() {
    SessionShutdownHook hook =
        new SessionShutdownHook(
            () -> true,
            () -> {
              throw new IllegalStateException("private-session-placeholder");
            });

    assertDoesNotThrow(hook::run);
  }

  @Test
  void interruptionDoesNotPreventJvmShutdownAndKeepsTheInterruptFlag() {
    SessionShutdownHook hook =
        new SessionShutdownHook(
            () -> true,
            () -> {
              throw new InterruptedException("private-session-placeholder");
            });

    assertDoesNotThrow(hook::run);

    // Thread.interrupted() also clears the flag so that it does not leak into other tests.
    assertTrue(Thread.interrupted());
  }

  @Test
  void failedCloseIsNotRetried() {
    AtomicInteger closeCalls = new AtomicInteger();
    SessionShutdownHook hook =
        new SessionShutdownHook(
            () -> true,
            () -> {
              closeCalls.incrementAndGet();
              throw new IOException("private-session-placeholder");
            });

    hook.run();

    assertEquals(1, closeCalls.get());
  }

  @Test
  void failureLogDoesNotIncludeTheExceptionMessage() {
    List<String> messages = new ArrayList<>();
    Handler handler =
        new Handler() {
          @Override
          public void publish(LogRecord record) {
            messages.add(record.getMessage());
          }

          @Override
          public void flush() {}

          @Override
          public void close() {}
        };
    Logger logger = Logger.getLogger(SessionShutdownHook.class.getName());
    logger.addHandler(handler);
    try {
      new SessionShutdownHook(
              () -> true,
              () -> {
                throw new IOException("private-session-placeholder");
              })
          .run();
    } finally {
      logger.removeHandler(handler);
    }

    assertEquals(1, messages.size());
    assertFalse(messages.get(0).contains("private-session-placeholder"));
  }

  @Test
  void rejectsMissingDependencies() {
    assertThrows(IllegalArgumentException.class, () -> new SessionShutdownHook(null, () -> {}));
    assertThrows(IllegalArgumentException.class, () -> new SessionShutdownHook(() -> true, null));
  }
}
