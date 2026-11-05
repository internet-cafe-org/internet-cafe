package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;

class AppLockTest {

  @Test
  void acquireAndRelease(@TempDir Path tempDir) throws IOException {
    // Override the lock directory via system property (tested via reflection on resolveLockFile
    // is not feasible; instead we verify the behaviour indirectly via a second acquire attempt)
    System.setProperty("user.home", tempDir.toString());
    // Unset APPDATA so the fallback path is used
    // (env vars can't be changed at runtime; the test relies on user.home fallback)
    try (AppLock lock = AppLock.acquire()) {
      assertNotNull(lock);
      // A second acquire while the first is held must throw
      assertThrows(AppLock.AlreadyRunningException.class, AppLock::acquire);
    }
    // After closing, a new acquire must succeed
    try (AppLock lock2 = AppLock.acquire()) {
      assertNotNull(lock2);
    }
  }

  @Test
  void alreadyRunningExceptionHasMessage() {
    AppLock.AlreadyRunningException ex = new AppLock.AlreadyRunningException();
    assertTrue(ex.getMessage().contains("already running"));
  }
}
