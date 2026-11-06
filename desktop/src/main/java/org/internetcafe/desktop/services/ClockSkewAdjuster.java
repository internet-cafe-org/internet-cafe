package org.internetcafe.desktop.services;

import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Logger;

/**
 * Tracks the clock offset between this machine and the API server.
 *
 * <p>When the backend rejects a signed request with {@code MACHINE_CLOCK_SKEW} it includes a
 * {@code Date} header with the server's current time. {@link #applyFromDateHeader(String)} computes
 * {@code serverTime − localTime} and stores it atomically so that subsequent requests can use
 * {@link #now()} to produce a timestamp the server will accept.
 *
 * <p>Thread-safe: all state is held in an {@link AtomicLong}.
 */
public final class ClockSkewAdjuster {

  private static final Logger log = Logger.getLogger(ClockSkewAdjuster.class.getName());

  /** RFC 1123 / HTTP-date format: {@code EEE, dd MMM yyyy HH:mm:ss z} */
  private static final DateTimeFormatter RFC_1123 = DateTimeFormatter.RFC_1123_DATE_TIME;

  /** Stored offset: serverTime − localTime in milliseconds. Positive = server is ahead. */
  private final AtomicLong offsetMillis = new AtomicLong(0L);

  /**
   * Returns the adjusted current time: local clock shifted by the stored offset. Use this instead
   * of {@link Instant#now()} when constructing request timestamps or signatures.
   */
  public Instant now() {
    return Instant.now().plusMillis(offsetMillis.get());
  }

  /**
   * Returns the stored offset in milliseconds.
   *
   * <p>Positive means the server clock is ahead of the local clock; negative means it is behind.
   * Zero means no skew has been recorded yet.
   */
  public long offsetMillis() {
    return offsetMillis.get();
  }

  /**
   * Parses the value of the HTTP {@code Date} response header and stores the computed skew.
   *
   * <p>The skew is {@code serverTime − localTime}: a positive value means the server is ahead and
   * the machine's clock should be advanced when signing.
   *
   * @param dateHeaderValue the raw value of the {@code Date} header; {@code null} or blank is
   *     silently ignored and returns {@code false}
   * @return {@code true} if the header was parsed successfully and the offset was updated
   */
  public boolean applyFromDateHeader(String dateHeaderValue) {
    if (dateHeaderValue == null || dateHeaderValue.isBlank()) {
      log.warning("MACHINE_CLOCK_SKEW: Date header is missing or blank — cannot correct skew");
      return false;
    }
    try {
      Instant serverTime = ZonedDateTime.parse(dateHeaderValue.trim(), RFC_1123).toInstant();
      Instant localTime = Instant.now();
      long skew = serverTime.toEpochMilli() - localTime.toEpochMilli();
      offsetMillis.set(skew);
      log.info(
          "Clock skew corrected: "
              + skew
              + " ms (server "
              + (skew >= 0 ? "ahead" : "behind")
              + " by "
              + Math.abs(skew)
              + " ms)");
      return true;
    } catch (DateTimeParseException e) {
      log.warning(
          "MACHINE_CLOCK_SKEW: could not parse Date header \""
              + dateHeaderValue
              + "\": "
              + e.getMessage());
      return false;
    }
  }

  /** Resets the stored offset to zero. Intended for tests. */
  public void reset() {
    offsetMillis.set(0L);
  }
}
