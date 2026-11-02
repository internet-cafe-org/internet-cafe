package org.internetcafe.desktop.screens;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class BoardScreenModelTest {

  private static final Instant START = Instant.parse("2026-10-30T14:00:00Z");

  private static Clock clockAt(String iso) {
    return Clock.fixed(Instant.parse(iso), ZoneOffset.UTC);
  }

  private static BoardScreenModel model(String code, Clock clock) {
    return new BoardScreenModel("Ana Perez", code, START, clock);
  }

  @Test
  void masksAllButLastTwoCharacters() {
    assertEquals("****34", model("20241234", clockAt("2026-10-30T14:00:00Z")).maskedCode());
  }

  @Test
  void masksShortCodesCompletely() {
    assertEquals("****", model("1234", clockAt("2026-10-30T14:00:00Z")).maskedCode());
  }

  @Test
  void formatsElapsedTimeAsHoursMinutesSeconds() {
    BoardScreenModel model = model("20241234", clockAt("2026-10-30T15:02:03Z"));
    assertEquals("01:02:03", model.elapsedLabel());
  }

  @Test
  void elapsedIsZeroAtStartAndNeverNegative() {
    assertEquals("00:00:00", model("20241234", clockAt("2026-10-30T14:00:00Z")).elapsedLabel());
    assertEquals("00:00:00", model("20241234", clockAt("2026-10-30T13:59:00Z")).elapsedLabel());
  }

  @Test
  void showsStartTimeInTheClockZone() {
    assertEquals("14:00:00", model("20241234", clockAt("2026-10-30T14:05:00Z")).startTimeLabel());
  }

  @Test
  void rejectsBlankNameCodeOrMissingStart() {
    Clock clock = clockAt("2026-10-30T14:00:00Z");
    assertThrows(
        IllegalArgumentException.class, () -> new BoardScreenModel(" ", "20241234", START, clock));
    assertThrows(
        IllegalArgumentException.class, () -> new BoardScreenModel("Ana", "", START, clock));
    assertThrows(
        IllegalArgumentException.class, () -> new BoardScreenModel("Ana", "20241234", null, clock));
  }
}
