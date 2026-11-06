package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.*;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Tests the MACHINE_CLOCK_SKEW detection and retry logic in {@link ApiClient}.
 *
 * <p>Uses an embedded HTTP server to simulate backend responses without network access.
 *
 * <p><b>Note on Date headers:</b> {@code com.sun.net.httpserver.HttpServer} automatically appends
 * its own {@code Date} header after {@code sendResponseHeaders}, which the JDK {@link HttpClient}
 * reads in preference to any header set via {@code exchange.getResponseHeaders()}. Tests that
 * require precise control of the {@code Date} value therefore exercise {@link ClockSkewAdjuster}
 * directly rather than relying on the embedded server.
 */
class ApiClientSkewTest {

  private HttpServer server;
  private ApiClient apiClient;
  private ClockSkewAdjuster skewAdjuster;
  private String baseUrl;

  @BeforeEach
  void setUp() throws IOException {
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.start();
    int port = server.getAddress().getPort();
    baseUrl = "http://127.0.0.1:" + port;
    skewAdjuster = new ClockSkewAdjuster();
    HttpClient httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    apiClient = new ApiClient(httpClient, baseUrl, skewAdjuster);
  }

  @AfterEach
  void tearDown() {
    server.stop(0);
  }

  // ── isClockSkewError helper ───────────────────────────────────────────────

  @Test
  void isClockSkewError_bodyContainsCode_returnsTrue() {
    assertTrue(ApiClient.isClockSkewError("{\"code\":\"MACHINE_CLOCK_SKEW\",\"status\":401}"));
  }

  @Test
  void isClockSkewError_bodyDoesNotContainCode_returnsFalse() {
    assertFalse(ApiClient.isClockSkewError("{\"code\":\"UNAUTHORIZED\",\"status\":401}"));
  }

  @Test
  void isClockSkewError_nullBody_returnsFalse() {
    assertFalse(ApiClient.isClockSkewError(null));
  }

  @Test
  void isClockSkewError_emptyBody_returnsFalse() {
    assertFalse(ApiClient.isClockSkewError(""));
  }

  // ── ClockSkewAdjuster unit tests (no HTTP server needed) ──────────────────

  /**
   * Verifies that {@link ClockSkewAdjuster#applyFromDateHeader} rejects null, blank, and
   * syntactically invalid header values without changing the stored offset. This exercises the
   * branch in {@link ApiClient} where the Date header is missing or unparseable.
   */
  @Test
  void applyFromDateHeader_nullBlankAndInvalidValues_returnFalseAndKeepZeroOffset() {
    ClockSkewAdjuster adjuster = new ClockSkewAdjuster();

    assertFalse(adjuster.applyFromDateHeader(null), "null header must return false");
    assertEquals(0L, adjuster.offsetMillis(), "offset must stay 0 for null header");

    assertFalse(adjuster.applyFromDateHeader(""), "empty header must return false");
    assertEquals(0L, adjuster.offsetMillis(), "offset must stay 0 for empty header");

    assertFalse(
        adjuster.applyFromDateHeader("not-a-valid-date"), "invalid date must return false");
    assertEquals(0L, adjuster.offsetMillis(), "offset must stay 0 for unparseable header");
  }

  /**
   * Verifies that a valid RFC 1123 Date header updates the offset to roughly the expected skew.
   * Uses a 10-second future timestamp; allows ±1200 ms for RFC 1123 second-precision truncation
   * and processing delay.
   */
  @Test
  void applyFromDateHeader_validFutureDate_setsPositiveOffset() {
    ClockSkewAdjuster adjuster = new ClockSkewAdjuster();
    Instant serverTime = Instant.now().plusSeconds(10);
    String header = formatRfc1123(serverTime);

    assertTrue(adjuster.applyFromDateHeader(header), "valid header must return true");
    long offset = adjuster.offsetMillis();
    // Expected ≈ 10000 ms; RFC 1123 drops sub-second precision → min ≈ 8800 ms
    assertTrue(
        offset >= 8800L && offset <= 10001L,
        "Expected offset in [8800, 10000] ms for 10 s skew, got " + offset);
  }

  // ── Retry on MACHINE_CLOCK_SKEW (integration via embedded HttpServer) ──────

  /**
   * Verifies that a MACHINE_CLOCK_SKEW 401 triggers exactly one retry and that the second call
   * succeeds. The callCount assertion is the primary check; the offset range is wide because
   * HttpServer auto-adds its own Date header which may be read by the JDK HttpClient.
   */
  @Test
  void skewRetry_firstRequestFails401WithSkew_secondSucceeds_retryHappens() throws Exception {
    AtomicInteger callCount = new AtomicInteger(0);
    Instant serverTime = Instant.now().plusSeconds(8);
    String dateHeader = formatRfc1123(serverTime);
    String healthBody = "{\"status\":\"ok\",\"service\":\"backend\"}";

    server.createContext(
        "/healthz",
        exchange -> {
          int call = callCount.incrementAndGet();
          try (exchange) {
            exchange.getRequestBody().readAllBytes();
            if (call == 1) {
              String body = "{\"code\":\"MACHINE_CLOCK_SKEW\",\"detail\":\"clock too far off\"}";
              byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
              exchange.getResponseHeaders().set("Content-Type", "application/json");
              exchange.getResponseHeaders().set("Date", dateHeader);
              exchange.sendResponseHeaders(401, bytes.length);
              exchange.getResponseBody().write(bytes);
            } else {
              byte[] bytes = healthBody.getBytes(StandardCharsets.UTF_8);
              exchange.getResponseHeaders().set("Content-Type", "application/json");
              exchange.sendResponseHeaders(200, bytes.length);
              exchange.getResponseBody().write(bytes);
            }
          }
        });

    assertDoesNotThrow(() -> apiClient.getHealth());
    assertEquals(2, callCount.get(), "Expected exactly 2 calls (original + retry)");
    // Offset may be near 0 (server auto-Date) or up to 8000 (our Date); either is valid.
    long offset = skewAdjuster.offsetMillis();
    assertTrue(
        offset >= -1000L && offset <= 8001L,
        "Offset out of plausible range [-1000, 8001] ms, got " + offset);
  }

  @Test
  void skewRetry_regularUnauthorized_throwsWithoutRetry() throws Exception {
    AtomicInteger callCount = new AtomicInteger(0);

    server.createContext(
        "/healthz",
        exchange -> {
          callCount.incrementAndGet();
          try (exchange) {
            exchange.getRequestBody().readAllBytes();
            String body = "{\"code\":\"UNAUTHORIZED\",\"detail\":\"invalid token\"}";
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(401, bytes.length);
            exchange.getResponseBody().write(bytes);
          }
        });

    ApiException ex = assertThrows(ApiException.class, () -> apiClient.getHealth());
    assertEquals(401, ex.getStatusCode());
    assertEquals(1, callCount.get(), "No retry expected for non-skew 401");
  }

  @Test
  void skewRetry_bothRequestsFail_throwsOnSecond() throws Exception {
    AtomicInteger callCount = new AtomicInteger(0);
    Instant serverTime = Instant.now().plusSeconds(5);
    String dateHeader = formatRfc1123(serverTime);

    server.createContext(
        "/healthz",
        exchange -> {
          callCount.incrementAndGet();
          try (exchange) {
            exchange.getRequestBody().readAllBytes();
            String body = "{\"code\":\"MACHINE_CLOCK_SKEW\"}";
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.getResponseHeaders().set("Date", dateHeader);
            exchange.sendResponseHeaders(401, bytes.length);
            exchange.getResponseBody().write(bytes);
          }
        });

    ApiException ex = assertThrows(ApiException.class, () -> apiClient.getHealth());
    assertEquals(401, ex.getStatusCode());
    assertEquals(2, callCount.get(), "Expected 2 calls: original + one retry");
  }

  @Test
  void skewAdjuster_exposedViaGetter() {
    assertSame(skewAdjuster, apiClient.skewAdjuster());
  }

  // ── Helper ────────────────────────────────────────────────────────────────

  private static String formatRfc1123(Instant instant) {
    return DateTimeFormatter.RFC_1123_DATE_TIME.format(
        ZonedDateTime.ofInstant(instant, ZoneOffset.UTC));
  }
}
