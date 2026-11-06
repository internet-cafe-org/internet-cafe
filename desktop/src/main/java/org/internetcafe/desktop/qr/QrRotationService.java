package org.internetcafe.desktop.qr;

import com.google.zxing.common.BitMatrix;
import java.io.IOException;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.LongSupplier;
import java.util.logging.Logger;
import org.internetcafe.desktop.contract.ChallengeResponse;

/**
 * Requests a new login challenge before the current QR expires, regenerates the image, and restarts
 * the countdown. Backend failures are retried a limited number of times; the last valid QR is kept
 * until it expires.
 */
public final class QrRotationService implements AutoCloseable {

  public static final int DEFAULT_MARGIN_SECONDS = 5;
  public static final int DEFAULT_MAX_ATTEMPTS = 3;
  public static final int DEFAULT_QR_SIZE = 320;

  private static final long NANOS_PER_SECOND = 1_000_000_000L;
  private static final Logger log = Logger.getLogger(QrRotationService.class.getName());

  private final ChallengeFetcher fetcher;
  private final Listener listener;
  private final int marginSeconds;
  private final int maxAttempts;
  private final int qrSize;
  private final LongSupplier clock;
  private final Scheduler scheduler;
  private final AtomicBoolean running = new AtomicBoolean();

  @FunctionalInterface
  public interface ChallengeFetcher {
    ChallengeResponse fetch() throws IOException, InterruptedException;
  }

  @FunctionalInterface
  public interface Listener {
    void onChallengeReady(BitMatrix qr, QrCountdown countdown);
  }

  interface Scheduler {
    void schedule(Runnable command, long delayNanos);

    void cancelPending();

    void shutdown();
  }

  public QrRotationService(ChallengeFetcher fetcher, Listener listener) {
    this(
        fetcher,
        listener,
        DEFAULT_MARGIN_SECONDS,
        DEFAULT_MAX_ATTEMPTS,
        DEFAULT_QR_SIZE,
        System::nanoTime,
        new ExecutorScheduler());
  }

  public QrRotationService(
      ChallengeFetcher fetcher, Listener listener, int marginSeconds, int maxAttempts) {
    this(
        fetcher,
        listener,
        marginSeconds,
        maxAttempts,
        DEFAULT_QR_SIZE,
        System::nanoTime,
        new ExecutorScheduler());
  }

  QrRotationService(
      ChallengeFetcher fetcher,
      Listener listener,
      int marginSeconds,
      int maxAttempts,
      int qrSize,
      LongSupplier clock,
      Scheduler scheduler) {
    if (fetcher == null || listener == null || clock == null || scheduler == null) {
      throw new IllegalArgumentException("QR rotation dependencies must not be null");
    }
    if (marginSeconds < 0) {
      throw new IllegalArgumentException("Refresh margin must not be negative");
    }
    if (maxAttempts < 1) {
      throw new IllegalArgumentException("Max attempts must be at least 1");
    }
    if (qrSize <= 0) {
      throw new IllegalArgumentException("QR size must be greater than zero");
    }
    this.fetcher = fetcher;
    this.listener = listener;
    this.marginSeconds = marginSeconds;
    this.maxAttempts = maxAttempts;
    this.qrSize = qrSize;
    this.clock = clock;
    this.scheduler = scheduler;
  }

  /** Starts the first challenge request on the scheduler thread. */
  public void start() {
    if (!running.compareAndSet(false, true)) {
      return;
    }
    scheduler.schedule(this::refresh, 0L);
  }

  /** Cancels pending work and shuts down the scheduler. Safe to call more than once. */
  public void stop() {
    running.set(false);
    scheduler.cancelPending();
    scheduler.shutdown();
  }

  @Override
  public void close() {
    stop();
  }

  private void refresh() {
    if (!running.get()) {
      return;
    }
    for (int attempt = 1; attempt <= maxAttempts; attempt++) {
      if (!running.get()) {
        return;
      }
      try {
        ChallengeResponse challenge = fetcher.fetch();
        BitMatrix qr = QrGenerator.generate(challenge.qrUrl(), qrSize);
        QrCountdown countdown = new QrCountdown(challenge.rotateAfterSeconds(), clock);
        listener.onChallengeReady(qr, countdown);
        log.info("QR challenge refreshed");
        scheduleNext(challenge.rotateAfterSeconds());
        return;
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        log.warning("QR challenge refresh interrupted");
        return;
      } catch (RuntimeException | IOException e) {
        log.warning("QR challenge refresh failed (attempt " + attempt + " of " + maxAttempts + ")");
      }
    }
    log.warning("QR challenge refresh exhausted retries; keeping the last valid QR");
  }

  private void scheduleNext(int rotateAfterSeconds) {
    if (!running.get()) {
      return;
    }
    long delaySeconds = Math.max(1L, (long) rotateAfterSeconds - marginSeconds);
    scheduler.cancelPending();
    scheduler.schedule(this::refresh, delaySeconds * NANOS_PER_SECOND);
  }

  private static final class ExecutorScheduler implements Scheduler {
    private final ScheduledExecutorService executor =
        Executors.newSingleThreadScheduledExecutor(
            runnable -> {
              Thread thread = new Thread(runnable, "qr-rotation");
              thread.setDaemon(true);
              return thread;
            });
    private volatile ScheduledFuture<?> pending;

    @Override
    public void schedule(Runnable command, long delayNanos) {
      pending = executor.schedule(command, delayNanos, TimeUnit.NANOSECONDS);
    }

    @Override
    public void cancelPending() {
      ScheduledFuture<?> current = pending;
      if (current != null) {
        current.cancel(false);
      }
    }

    @Override
    public void shutdown() {
      cancelPending();
      executor.shutdownNow();
    }
  }
}
