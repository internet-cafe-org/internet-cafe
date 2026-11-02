package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;
import org.junit.jupiter.api.Test;

class ChallengeWaitServiceTest {

  private static final Instant NOW = Instant.parse("2026-10-31T15:00:00Z");
  private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);

  private static final ChallengeWaitResponse WAITING =
      new ChallengeWaitResponse("waiting", null, null);
  private static final ChallengeWaitResponse APPROVED =
      new ChallengeWaitResponse(
          "approved",
          new ChallengeWaitResponse.Session("session-1", "active", "2026-10-31T15:00:00Z"),
          new ChallengeWaitResponse.User("Ana Perez", "2021****34"));

  @Test
  void approvedStopsRotationBeforeNotifyingTheListener() throws Exception {
    List<String> events = new CopyOnWriteArrayList<>();
    CountDownLatch approved = new CountDownLatch(1);
    AtomicInteger calls = new AtomicInteger();

    ChallengeWaitService service =
        new ChallengeWaitService(
            () -> calls.incrementAndGet() < 3 ? WAITING : APPROVED,
            () -> events.add("stop-rotation"),
            (response, approvedAt) -> {
              events.add("approved:" + approvedAt);
              approved.countDown();
            },
            1L,
            5L,
            CLOCK);

    service.start();

    assertTrue(approved.await(5, TimeUnit.SECONDS));
    assertEquals(List.of("stop-rotation", "approved:" + NOW), events);
    assertEquals(3, calls.get());
    assertEquals(ChallengeWaitService.State.APPROVED, service.state());
  }

  @Test
  void retriesAfterNetworkErrorsAndStillApproves() throws Exception {
    CountDownLatch approved = new CountDownLatch(1);
    AtomicInteger calls = new AtomicInteger();
    AtomicReference<ChallengeWaitResponse> received = new AtomicReference<>();

    ChallengeWaitService service =
        new ChallengeWaitService(
            () -> {
              if (calls.incrementAndGet() <= 2) {
                throw new IOException("backend unavailable");
              }
              return APPROVED;
            },
            () -> {},
            (response, approvedAt) -> {
              received.set(response);
              approved.countDown();
            },
            1L,
            5L,
            CLOCK);

    service.start();

    assertTrue(approved.await(5, TimeUnit.SECONDS));
    assertEquals(3, calls.get());
    assertSame(APPROVED, received.get());
  }

  @Test
  void stopInterruptsThePendingRequestAndNeverApproves() throws Exception {
    CountDownLatch polling = new CountDownLatch(1);
    CountDownLatch interrupted = new CountDownLatch(1);
    AtomicInteger approvals = new AtomicInteger();

    ChallengeWaitService service =
        new ChallengeWaitService(
            () -> {
              polling.countDown();
              try {
                new CountDownLatch(1).await();
              } catch (InterruptedException e) {
                interrupted.countDown();
                throw e;
              }
              return APPROVED;
            },
            () -> {},
            (response, approvedAt) -> approvals.incrementAndGet(),
            1L,
            5L,
            CLOCK);

    service.start();
    assertTrue(polling.await(5, TimeUnit.SECONDS));

    service.stop();

    assertTrue(interrupted.await(5, TimeUnit.SECONDS));
    assertEquals(ChallengeWaitService.State.STOPPED, service.state());
    assertEquals(0, approvals.get());
  }
}
