package org.internetcafe.desktop.qr;

/**
 * Exponential retry delays in seconds: 2, 4, 8, 16, 30, 30... Not thread-safe; use it from a single
 * worker thread.
 */
public final class ExponentialBackoff {

  public static final long INITIAL_DELAY_SECONDS = 2L;
  public static final long MAX_DELAY_SECONDS = 30L;

  private final long initialDelaySeconds;
  private final long maxDelaySeconds;
  private long nextDelaySeconds;

  public ExponentialBackoff() {
    this(INITIAL_DELAY_SECONDS, MAX_DELAY_SECONDS);
  }

  public ExponentialBackoff(long initialDelaySeconds, long maxDelaySeconds) {
    if (initialDelaySeconds < 1 || maxDelaySeconds < initialDelaySeconds) {
      throw new IllegalArgumentException("Invalid backoff delays");
    }
    this.initialDelaySeconds = initialDelaySeconds;
    this.maxDelaySeconds = maxDelaySeconds;
    this.nextDelaySeconds = initialDelaySeconds;
  }

  /** Returns the delay to wait before the next attempt and grows the one that follows. */
  public long nextDelaySeconds() {
    long current = nextDelaySeconds;
    nextDelaySeconds = Math.min(current * 2, maxDelaySeconds);
    return current;
  }

  public void reset() {
    nextDelaySeconds = initialDelaySeconds;
  }
}
