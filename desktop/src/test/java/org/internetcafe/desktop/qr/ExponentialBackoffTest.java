package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class ExponentialBackoffTest {

  @Test
  void growsFrom2To30AndStaysAtTheCap() {
    ExponentialBackoff backoff = new ExponentialBackoff();
    List<Long> delays = new ArrayList<>();
    for (int i = 0; i < 7; i++) {
      delays.add(backoff.nextDelaySeconds());
    }
    assertEquals(List.of(2L, 4L, 8L, 16L, 30L, 30L, 30L), delays);
  }

  @Test
  void resetStartsOverFromTheInitialDelay() {
    ExponentialBackoff backoff = new ExponentialBackoff();
    backoff.nextDelaySeconds();
    backoff.nextDelaySeconds();

    backoff.reset();

    assertEquals(2L, backoff.nextDelaySeconds());
  }

  @Test
  void rejectsInvalidDelays() {
    assertThrows(IllegalArgumentException.class, () -> new ExponentialBackoff(0L, 30L));
    assertThrows(IllegalArgumentException.class, () -> new ExponentialBackoff(5L, 2L));
  }
}
