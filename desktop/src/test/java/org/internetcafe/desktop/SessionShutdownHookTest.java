package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicInteger;
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
}
