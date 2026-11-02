package org.internetcafe.desktop.qr;

import java.io.IOException;
import java.time.Clock;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicReference;
import java.util.logging.Logger;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;

/**
 * Long-polls the backend on a virtual thread until a student claims the machine's QR challenge.
 *
 * <p>States: IDLE (created), WAITING (polling), APPROVED (terminal, the QR was claimed) and
 * STOPPED (terminal, cancelled by the caller). When the backend answers {@code approved}, the QR
 * rotation is stopped first and then the listener is notified, exactly once. "Waiting" answers
 * start a new request, and network errors are retried with a growing delay, so the loop never
 * spins. Nothing from the responses is written to the log.
 */
public final class ChallengeWaitService implements AutoCloseable {

  public static final long DEFAULT_RETRY_DELAY_MILLIS = 1_000L;
  public static final long DEFAULT_MAX_RETRY_DELAY_MILLIS = 10_000L;

  private static final Logger log = Logger.getLogger(ChallengeWaitService.class.getName());

  /** Lifecycle of the wait. APPROVED and STOPPED are terminal. */
  public enum State {
    IDLE,
    WAITING,
    APPROVED,
    STOPPED
  }

  @FunctionalInterface
  public interface WaitFetcher {
    ChallengeWaitResponse fetch() throws IOException, InterruptedException;
  }

  @FunctionalInterface
  public interface ApprovedListener {
    void onApproved(ChallengeWaitResponse response, Instant approvedAt);
  }

  private final WaitFetcher fetcher;
  private final Runnable stopRotation;
  private final ApprovedListener listener;
  private final long retryDelayMillis;
  private final long maxRetryDelayMillis;
  private final Clock clock;
  private final AtomicReference<State> state = new AtomicReference<>(State.IDLE);
  private volatile Thread worker;

  public ChallengeWaitService(
      WaitFetcher fetcher, Runnable stopRotation, ApprovedListener listener) {
    this(
        fetcher,
        stopRotation,
        listener,
        DEFAULT_RETRY_DELAY_MILLIS,
        DEFAULT_MAX_RETRY_DELAY_MILLIS,
        Clock.systemUTC());
  }

  ChallengeWaitService(
      WaitFetcher fetcher,
      Runnable stopRotation,
      ApprovedListener listener,
      long retryDelayMillis,
      long maxRetryDelayMillis,
      Clock clock) {
    if (fetcher == null || stopRotation == null || listener == null || clock == null) {
      throw new IllegalArgumentException("Challenge wait dependencies must not be null");
    }
    if (retryDelayMillis < 0 || maxRetryDelayMillis < retryDelayMillis) {
      throw new IllegalArgumentException("Invalid retry delays");
    }
    this.fetcher = fetcher;
    this.stopRotation = stopRotation;
    this.listener = listener;
    this.retryDelayMillis = retryDelayMillis;
    this.maxRetryDelayMillis = maxRetryDelayMillis;
    this.clock = clock;
  }

  public State state() {
    return state.get();
  }

  /** Starts polling on a virtual thread. Calling it again, or after stop(), does nothing. */
  public void start() {
    if (!state.compareAndSet(State.IDLE, State.WAITING)) {
      return;
    }
    Thread thread = Thread.ofVirtual().name("challenge-wait").unstarted(this::pollUntilApproved);
    worker = thread;
    thread.start();
  }

  /** Cancels the wait and interrupts the pending request. Safe to call more than once. */
  public void stop() {
    State previous = state.getAndUpdate(s -> s == State.APPROVED ? s : State.STOPPED);
    if (previous == State.APPROVED) {
      return;
    }
    Thread thread = worker;
    if (thread != null && thread != Thread.currentThread()) {
      thread.interrupt();
    }
  }

  @Override
  public void close() {
    stop();
  }

  private void pollUntilApproved() {
    long delayMillis = retryDelayMillis;
    while (state.get() == State.WAITING) {
      ChallengeWaitResponse response;
      try {
        response = fetcher.fetch();
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        return;
      } catch (IOException | RuntimeException e) {
        if (state.get() != State.WAITING) {
          return;
        }
        log.warning("Long-poll request failed; retrying in " + delayMillis + " ms");
        if (!pause(delayMillis)) {
          return;
        }
        delayMillis = Math.min(delayMillis * 2, maxRetryDelayMillis);
        continue;
      }
      delayMillis = retryDelayMillis;
      if (response != null && response.approved()) {
        approve(response);
        return;
      }
    }
  }

  private void approve(ChallengeWaitResponse response) {
    if (!state.compareAndSet(State.WAITING, State.APPROVED)) {
      return;
    }
    Instant approvedAt = clock.instant();
    try {
      stopRotation.run();
      listener.onApproved(response, approvedAt);
    } catch (RuntimeException e) {
      log.warning("Approved handler failed");
    }
  }

  private static boolean pause(long millis) {
    try {
      Thread.sleep(millis);
      return true;
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      return false;
    }
  }
}
