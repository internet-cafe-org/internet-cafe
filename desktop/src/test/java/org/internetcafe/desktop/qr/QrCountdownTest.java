package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class QrCountdownTest {

  private static final long SECOND = 1_000_000_000L;

  @Test
  void remainingSecondsDecreasesAsTimePasses() {
    long[] now = {0L};
    QrCountdown countdown = new QrCountdown(30, () -> now[0]);

    assertEquals(30, countdown.remainingSeconds());
    now[0] = 10 * SECOND;
    assertEquals(20, countdown.remainingSeconds());
    assertFalse(countdown.isExpired());
  }

  @Test
  void expiresWhenDurationIsReached() {
    long[] now = {0L};
    QrCountdown countdown = new QrCountdown(30, () -> now[0]);

    now[0] = 30 * SECOND;

    assertTrue(countdown.isExpired());
    assertEquals(0, countdown.remainingSeconds());
  }

  @Test
  void restartStartsFromFullDuration() {
    long[] now = {0L};
    QrCountdown countdown = new QrCountdown(30, () -> now[0]);
    now[0] = 25 * SECOND;

    countdown.restart();

    assertEquals(30, countdown.remainingSeconds());
  }

  @Test
  void rejectsNonPositiveDuration() {
    assertThrows(IllegalArgumentException.class, () -> new QrCountdown(0));
  }
}
