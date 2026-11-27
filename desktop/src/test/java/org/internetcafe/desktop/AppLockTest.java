package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class AppLockTest {

  @AfterEach
  void clearLockDirOverride() {
    System.clearProperty(AppLock.LOCK_DIR_PROPERTY);
  }

  @Test
  void acquireAndRelease(@TempDir Path tempDir) throws IOException {
    System.setProperty(AppLock.LOCK_DIR_PROPERTY, tempDir.toString());
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
  void usesLockDirectoryOverride(@TempDir Path tempDir) throws IOException {
    System.setProperty(AppLock.LOCK_DIR_PROPERTY, tempDir.toString());
    try (AppLock lock = AppLock.acquire()) {
      assertNotNull(lock);
      assertTrue(Files.exists(tempDir.resolve("internet-cafe-desktop.lock")));
    }
  }

  @Test
  void alreadyRunningExceptionHasMessage() {
    AppLock.AlreadyRunningException ex = new AppLock.AlreadyRunningException();
    assertTrue(ex.getMessage().contains("already running"));
  }
}
