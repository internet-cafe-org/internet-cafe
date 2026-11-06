package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.*;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ClockSkewAdjusterTest {

  /**
   * RFC 1123 has only second precision. When we format an Instant and parse it back, we lose the
   * sub-second part (F ms, 0–999). The adjuster also calls Instant.now() after the parse, adding
   * δ ms of processing time. So the measured offset is:
   *
   * <pre>offset = expectedSkewMs − F − δ</pre>
   *
   * where F ∈ [0, 999] and δ ∈ [0, ~200]. All bounds below account for this.
   */
  private static final long TOLERANCE_MS = 1200L;

  private ClockSkewAdjuster adjuster;

  @BeforeEach
  void setUp() {
    adjuster = new ClockSkewAdjuster();
  }

  @Test
  void initialOffsetIsZero() {
    assertEquals(0L, adjuster.offsetMillis());
  }

  @Test
  void nowWithZeroOffsetIsCloseToInstantNow() {
    long delta = Math.abs(adjuster.now().toEpochMilli() - Instant.now().toEpochMilli());
    assertTrue(delta < 100, "Expected now() within 100 ms of Instant.now(), got delta=" + delta);
  }

  @Test
  void applyFromDateHeader_serverAhead_storesPositiveOffset() {
    // Server is 5 seconds ahead
    Instant serverTime = Instant.now().plusSeconds(5);
    String dateHeader = formatRfc1123(serverTime);

    boolean applied = adjuster.applyFromDateHeader(dateHeader);

    assertTrue(applied);
    // offset = 5000 - F - δ: max = 5000, min ≈ 5000 - 999 - 200 = 3800
    long offset = adjuster.offsetMillis();
    assertTrue(
        offset >= 5000L - TOLERANCE_MS && offset <= 5000L,
        "Expected offset in [" + (5000 - TOLERANCE_MS) + ", 5000] ms, got " + offset);
  }

  @Test
  void applyFromDateHeader_serverBehind_storesNegativeOffset() {
    // Server is 3 seconds behind
    Instant serverTime = Instant.now().minusSeconds(3);
    String dateHeader = formatRfc1123(serverTime);

    boolean applied = adjuster.applyFromDateHeader(dateHeader);

    assertTrue(applied);
    // offset = -3000 - F - δ: max = -3000, min ≈ -3000 - 999 - 200 = -4199
    long offset = adjuster.offsetMillis();
    assertTrue(
        offset <= -3000L + TOLERANCE_MS && offset >= -3000L - TOLERANCE_MS,
        "Expected offset near -3000 ms, got " + offset);
  }

  @Test
  void applyFromDateHeader_sameTime_offsetNonPositive() {
    // Server time is now — offset should be ≤ 0 (never positive due to truncation + processing)
    Instant serverTime = Instant.now();
    String dateHeader = formatRfc1123(serverTime);

    boolean applied = adjuster.applyFromDateHeader(dateHeader);

    assertTrue(applied);
    // offset = -F - δ: always ≤ 0, min ≈ -999 - 200 = -1199
    long offset = adjuster.offsetMillis();
    assertTrue(
        offset <= 0 && offset >= -TOLERANCE_MS,
        "Expected offset in [-" + TOLERANCE_MS + ", 0] ms, got " + offset);
  }

  @Test
  void applyFromDateHeader_nullValue_returnsFalse() {
    boolean applied = adjuster.applyFromDateHeader(null);

    assertFalse(applied);
    assertEquals(0L, adjuster.offsetMillis());
  }

  @Test
  void applyFromDateHeader_blankValue_returnsFalse() {
    boolean applied = adjuster.applyFromDateHeader("   ");

    assertFalse(applied);
    assertEquals(0L, adjuster.offsetMillis());
  }

  @Test
  void applyFromDateHeader_invalidFormat_returnsFalse() {
    boolean applied = adjuster.applyFromDateHeader("not-a-date");

    assertFalse(applied);
    assertEquals(0L, adjuster.offsetMillis());
  }

  @Test
  void applyFromDateHeader_isoFormat_returnsFalse() {
    // ISO-8601 is not RFC 1123 — must not be accepted
    boolean applied = adjuster.applyFromDateHeader(Instant.now().toString());

    assertFalse(applied);
  }

  @Test
  void nowReflectsStoredOffset() {
    // Apply a known 10-second ahead offset
    Instant serverTime = Instant.now().plusSeconds(10);
    adjuster.applyFromDateHeader(formatRfc1123(serverTime));

    // adjuster.now() = Instant.now() + offset; delta vs plain Instant.now() ≈ offset ∈ [8800, 10000]
    long delta = adjuster.now().toEpochMilli() - Instant.now().toEpochMilli();
    assertTrue(
        delta >= 10000L - 2 * TOLERANCE_MS && delta <= 10000L,
        "Expected delta in [" + (10000 - 2 * TOLERANCE_MS) + ", 10000] ms, got " + delta);
  }

  @Test
  void resetClearsOffset() {
    adjuster.applyFromDateHeader(formatRfc1123(Instant.now().plusSeconds(60)));
    assertNotEquals(0L, adjuster.offsetMillis());

    adjuster.reset();

    assertEquals(0L, adjuster.offsetMillis());
  }

  @Test
  void multipleApplicationsOverwritePreviousOffset() {
    adjuster.applyFromDateHeader(formatRfc1123(Instant.now().plusSeconds(10)));
    assertTrue(adjuster.offsetMillis() > 0, "First offset should be positive");

    adjuster.applyFromDateHeader(formatRfc1123(Instant.now().minusSeconds(5)));
    assertTrue(adjuster.offsetMillis() < 0, "Second offset should be negative");
  }

  @Test
  void applyFromDateHeader_trailingWhitespace_parsedCorrectly() {
    String dateHeader = "  " + formatRfc1123(Instant.now().plusSeconds(2)) + "  ";

    boolean applied = adjuster.applyFromDateHeader(dateHeader);

    assertTrue(applied);
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  private static String formatRfc1123(Instant instant) {
    return DateTimeFormatter.RFC_1123_DATE_TIME.format(
        ZonedDateTime.ofInstant(instant, ZoneOffset.UTC));
  }
}
