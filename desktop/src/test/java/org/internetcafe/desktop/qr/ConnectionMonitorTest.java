package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.internetcafe.desktop.qr.ConnectionMonitor.Phase;
import org.internetcafe.desktop.qr.ConnectionMonitor.Status;
import org.junit.jupiter.api.Test;

class ConnectionMonitorTest {

  /** First countdown value published after each failed attempt, in order. */
  private static Map<Integer, Long> firstCountdownPerFailure(List<Status> statuses) {
    Map<Integer, Long> result = new LinkedHashMap<>();
    for (Status status : statuses) {
      if (status.nextAttemptInSeconds() > 0) {
        result.putIfAbsent(status.failedAttempts(), status.nextAttemptInSeconds());
      }
    }
    return result;
  }

  @Test
  void retriesWithGrowingDelaysAndReportsRestored() throws Exception {
    AtomicInteger calls = new AtomicInteger();
    List<Status> statuses = new CopyOnWriteArrayList<>();
    CountDownLatch restored = new CountDownLatch(1);

    ConnectionMonitor monitor =
        new ConnectionMonitor(
            () -> {
              if (calls.incrementAndGet() <= 3) {
                throw new IOException("down");
              }
            },
            status -> {
              statuses.add(status);
              if (status.phase() == Phase.RESTORED) {
                restored.countDown();
              }
            },
            () -> {});

    monitor.reportFailure();

    assertTrue(restored.await(5, TimeUnit.SECONDS));
    assertEquals(4, calls.get());
    assertEquals(Map.of(1, 2L, 2, 4L, 3, 8L), firstCountdownPerFailure(statuses));
    assertEquals(Phase.CONNECTING, statuses.get(0).phase());
    assertEquals(Phase.RESTORED, statuses.get(statuses.size() - 1).phase());
    assertTrue(statuses.stream().noneMatch(s -> s.phase() == Phase.PROLONGED));
    assertFalse(monitor.isActive());
  }

  @Test
  void becomesProlongedAfterFiveFailuresAndKeepsRetryingUpTo30Seconds() throws Exception {
    AtomicInteger calls = new AtomicInteger();
    List<Status> statuses = new CopyOnWriteArrayList<>();
    CountDownLatch restored = new CountDownLatch(1);

    ConnectionMonitor monitor =
        new ConnectionMonitor(
            () -> {
              if (calls.incrementAndGet() <= 6) {
                throw new IOException("down");
              }
            },
            status -> {
              statuses.add(status);
              if (status.phase() == Phase.RESTORED) {
                restored.countDown();
              }
            },
            () -> {});

    monitor.reportFailure();

    assertTrue(restored.await(5, TimeUnit.SECONDS));
    assertEquals(
        Map.of(1, 2L, 2, 4L, 3, 8L, 4, 16L, 5, 30L, 6, 30L), firstCountdownPerFailure(statuses));
    assertTrue(
        statuses.stream().anyMatch(s -> s.phase() == Phase.PROLONGED && s.failedAttempts() == 5));
    assertTrue(
        statuses.stream().noneMatch(s -> s.phase() == Phase.PROLONGED && s.failedAttempts() < 5));
  }

  @Test
  void retryNowSkipsTheWaitAndChecksImmediately() throws Exception {
    AtomicInteger calls = new AtomicInteger();
    CountDownLatch waiting = new CountDownLatch(1);
    CountDownLatch restored = new CountDownLatch(1);

    ConnectionMonitor monitor =
        new ConnectionMonitor(
            () -> {
              if (calls.incrementAndGet() == 1) {
                throw new IOException("down");
              }
            },
            status -> {
              if (status.phase() == Phase.RETRYING) {
                waiting.countDown();
              }
              if (status.phase() == Phase.RESTORED) {
                restored.countDown();
              }
            },
            () -> Thread.sleep(60_000L));

    monitor.reportFailure();
    assertTrue(waiting.await(5, TimeUnit.SECONDS));

    monitor.retryNow();

    assertTrue(restored.await(5, TimeUnit.SECONDS));
    assertEquals(2, calls.get());
  }

  @Test
  void stopCancelsTheCycleAndTheMonitorCanBeStartedAgain() throws Exception {
    AtomicBoolean down = new AtomicBoolean(true);
    AtomicInteger restoredCount = new AtomicInteger();
    CountDownLatch retrying = new CountDownLatch(1);
    CountDownLatch restored = new CountDownLatch(1);

    ConnectionMonitor monitor =
        new ConnectionMonitor(
            () -> {
              if (down.get()) {
                throw new IOException("down");
              }
            },
            status -> {
              if (status.phase() == Phase.RETRYING) {
                retrying.countDown();
              }
              if (status.phase() == Phase.RESTORED) {
                restoredCount.incrementAndGet();
                restored.countDown();
              }
            },
            () -> Thread.sleep(10L));

    monitor.reportFailure();
    assertTrue(retrying.await(5, TimeUnit.SECONDS));

    monitor.stop();
    assertFalse(monitor.isActive());

    down.set(false);
    monitor.reportFailure();

    assertTrue(restored.await(5, TimeUnit.SECONDS));
    Thread.sleep(200L);
    assertEquals(1, restoredCount.get());
  }
}
