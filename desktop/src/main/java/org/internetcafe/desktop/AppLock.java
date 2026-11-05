package org.internetcafe.desktop;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.logging.Logger;

/**
 * Guarantees that only one instance of the application runs at a time by holding an exclusive
 * {@link FileLock} on a well-known file inside the user's application-data directory.
 *
 * <p>Usage:
 *
 * <pre>{@code
 * try (AppLock lock = AppLock.acquire()) {
 *   // run the application
 * }
 * }</pre>
 *
 * <p>If the lock cannot be obtained (another instance is already running) {@link #acquire()} throws
 * {@link AlreadyRunningException}.
 */
public final class AppLock implements AutoCloseable {

  private static final Logger log = Logger.getLogger(AppLock.class.getName());
  private static final String LOCK_FILE_NAME = "internet-cafe-desktop.lock";

  /** Thrown when another instance already holds the lock. */
  public static final class AlreadyRunningException extends RuntimeException {
    public AlreadyRunningException() {
      super("Another instance of Internet Cafe Desktop is already running.");
    }
  }

  private final FileChannel channel;
  private final FileLock lock;

  private AppLock(FileChannel channel, FileLock lock) {
    this.channel = channel;
    this.lock = lock;
  }

  /**
   * Tries to acquire the application lock.
   *
   * @return an {@link AppLock} that must be closed when the application exits
   * @throws AlreadyRunningException if another instance already holds the lock
   * @throws IOException if the lock file cannot be created or opened
   */
  public static AppLock acquire() throws IOException {
    Path lockFile = resolveLockFile();
    log.info("Acquiring application lock at: " + lockFile);

    FileChannel channel =
        FileChannel.open(
            lockFile,
            StandardOpenOption.CREATE,
            StandardOpenOption.WRITE,
            StandardOpenOption.READ);

    FileLock lock;
    try {
      lock = channel.tryLock();
    } catch (OverlappingFileLockException e) {
      // Same JVM already holds the lock (happens in tests or if acquire() is called twice)
      channel.close();
      throw new AlreadyRunningException();
    }
    if (lock == null) {
      channel.close();
      throw new AlreadyRunningException();
    }

    log.info("Application lock acquired.");
    return new AppLock(channel, lock);
  }

  /** Releases the lock and closes the underlying file channel. */
  @Override
  public void close() {
    try {
      lock.release();
      channel.close();
      log.info("Application lock released.");
    } catch (IOException e) {
      log.warning("Failed to release application lock: " + e.getMessage());
    }
  }

  private static Path resolveLockFile() {
    // %APPDATA% on Windows; fall back to user.home on other systems
    String appData = System.getenv("APPDATA");
    Path dir =
        (appData != null && !appData.isBlank())
            ? Path.of(appData, "InternetCafe")
            : Path.of(System.getProperty("user.home"), ".internet-cafe");

    try {
      java.nio.file.Files.createDirectories(dir);
    } catch (IOException e) {
      log.warning("Could not create lock directory, using temp dir: " + e.getMessage());
      dir = Path.of(System.getProperty("java.io.tmpdir"));
    }

    return dir.resolve(LOCK_FILE_NAME);
  }
}
