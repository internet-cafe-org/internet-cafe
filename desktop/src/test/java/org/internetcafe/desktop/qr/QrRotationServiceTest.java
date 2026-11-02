package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.google.zxing.common.BitMatrix;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.internetcafe.desktop.contract.ChallengeResponse;
import org.junit.jupiter.api.Test;

class QrRotationServiceTest {

  private static final long SECOND = 1_000_000_000L;

  @Test
  void rotatesAndRegeneratesQrBeforeExpiry() {
    ControllableClock clock = new ControllableClock();
    ManualScheduler scheduler = new ManualScheduler(clock);
    FakeChallengeFetcher fetcher =
        new FakeChallengeFetcher(
            challenge("https://front.example.invalid/s#one", 10),
            challenge("https://front.example.invalid/s#two", 10));
    List<BitMatrix> qrs = new ArrayList<>();
    List<QrCountdown> countdowns = new ArrayList<>();

    QrRotationService service =
        new QrRotationService(
            fetcher,
            (qr, countdown) -> {
              qrs.add(qr);
              countdowns.add(countdown);
            },
            2,
            3,
            200,
            clock::nanos,
            scheduler);

    service.start();
    scheduler.runDue();

    assertEquals(1, fetcher.calls);
    assertEquals(QrGenerator.generate("https://front.example.invalid/s#one", 200), qrs.get(0));
    assertEquals(10, countdowns.get(0).remainingSeconds());
    assertFalse(countdowns.get(0).isExpired());

    clock.advance(8 * SECOND);
    assertFalse(countdowns.get(0).isExpired());
    assertEquals(2, countdowns.get(0).remainingSeconds());

    scheduler.runDue();

    assertEquals(2, fetcher.calls);
    assertEquals(QrGenerator.generate("https://front.example.invalid/s#two", 200), qrs.get(1));
    assertNotEquals(qrs.get(0), qrs.get(1));
    assertEquals(10, countdowns.get(1).remainingSeconds());
    assertFalse(countdowns.get(1).isExpired());
  }

  @Test
  void retriesALimitedNumberOfTimesAndKeepsLastValidQr() {
    ControllableClock clock = new ControllableClock();
    ManualScheduler scheduler = new ManualScheduler(clock);
    FakeChallengeFetcher fetcher =
        new FakeChallengeFetcher(challenge("https://front.example.invalid/s#keep", 10));
    List<BitMatrix> qrs = new ArrayList<>();

    QrRotationService service =
        new QrRotationService(
            fetcher, (qr, countdown) -> qrs.add(qr), 2, 3, 200, clock::nanos, scheduler);

    service.start();
    scheduler.runDue();
    assertEquals(1, qrs.size());

    fetcher.failNext(3);
    clock.advance(8 * SECOND);
    scheduler.runDue();

    assertEquals(4, fetcher.calls);
    assertEquals(1, qrs.size());
    assertEquals(QrGenerator.generate("https://front.example.invalid/s#keep", 200), qrs.get(0));
    assertFalse(scheduler.hasPending());
  }

  @Test
  void stopCancelsPendingRefresh() {
    ControllableClock clock = new ControllableClock();
    ManualScheduler scheduler = new ManualScheduler(clock);
    FakeChallengeFetcher fetcher =
        new FakeChallengeFetcher(challenge("https://front.example.invalid/s#one", 10));

    QrRotationService service =
        new QrRotationService(fetcher, (qr, countdown) -> {}, 2, 3, 200, clock::nanos, scheduler);

    service.start();
    scheduler.runDue();
    assertTrue(scheduler.hasPending());

    service.stop();

    assertTrue(scheduler.shutdown);
    assertFalse(scheduler.hasPending());

    clock.advance(8 * SECOND);
    scheduler.runDue();
    assertEquals(1, fetcher.calls);
  }

  private static ChallengeResponse challenge(String qrUrl, int rotateAfterSeconds) {
    return new ChallengeResponse(
        "challenge-" + qrUrl.hashCode(), qrUrl, "2026-10-19T14:05:00Z", rotateAfterSeconds);
  }

  private static final class ControllableClock {
    private long nanos;

    long nanos() {
      return nanos;
    }

    void advance(long deltaNanos) {
      nanos += deltaNanos;
    }
  }

  private static final class ManualScheduler implements QrRotationService.Scheduler {
    private final ControllableClock clock;
    private Runnable pending;
    private long runAtNanos;
    private boolean shutdown;

    ManualScheduler(ControllableClock clock) {
      this.clock = clock;
    }

    @Override
    public void schedule(Runnable command, long delayNanos) {
      if (shutdown) {
        return;
      }
      pending = command;
      runAtNanos = clock.nanos() + delayNanos;
    }

    @Override
    public void cancelPending() {
      pending = null;
    }

    @Override
    public void shutdown() {
      shutdown = true;
      pending = null;
    }

    boolean hasPending() {
      return pending != null;
    }

    void runDue() {
      if (pending == null || clock.nanos() < runAtNanos) {
        return;
      }
      Runnable command = pending;
      pending = null;
      command.run();
    }
  }

  private static final class FakeChallengeFetcher implements QrRotationService.ChallengeFetcher {
    private final List<ChallengeResponse> responses;
    private int nextSuccess;
    private int remainingFailures;
    private int calls;

    FakeChallengeFetcher(ChallengeResponse... responses) {
      this.responses = List.of(responses);
    }

    void failNext(int count) {
      remainingFailures = count;
    }

    @Override
    public ChallengeResponse fetch() throws IOException {
      calls++;
      if (remainingFailures > 0) {
        remainingFailures--;
        throw new IOException("backend unavailable");
      }
      ChallengeResponse response = responses.get(Math.min(nextSuccess, responses.size() - 1));
      nextSuccess++;
      return response;
    }
  }
}
