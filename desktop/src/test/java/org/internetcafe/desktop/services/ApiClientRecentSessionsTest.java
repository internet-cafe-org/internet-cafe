package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.internetcafe.desktop.contract.RecentSession;
import org.internetcafe.desktop.signing.TestRequestSigner;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ApiClientRecentSessionsTest {
  private static final String CURRENT_SESSION_PATH = "/api/v1/machine/sessions/current";
  private static final String CURRENT_SESSION_BODY =
      "{\"session\":{\"id\":\"session-test\",\"status\":\"active\","
          + "\"started_at\":\"2026-11-17T08:00:10Z\"},\"user\":{},"
          + "\"recent_accesses\":["
          + "{\"machine_code\":\"LAB1-PC03\",\"lab\":\"Sala 1\","
          + "\"started_at\":\"2026-11-16T14:00:00Z\","
          + "\"ended_at\":\"2026-11-16T15:30:00Z\",\"duration_s\":5400},"
          + "{\"machine_code\":\"LAB2-PC01\",\"lab\":\"Sala 2\","
          + "\"started_at\":\"2026-11-15T09:00:00Z\","
          + "\"ended_at\":\"2026-11-15T09:45:00Z\",\"duration_s\":2700}]}";

  private final Map<String, String> requestHeaders = new ConcurrentHashMap<>();
  private volatile String requestMethod;
  private volatile boolean openSession = true;
  private HttpServer server;
  private String baseUrl;
  private ApiClient apiClient;

  @BeforeEach
  void startServer() throws Exception {
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/", this::handleRequest);
    server.start();
    baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
    apiClient =
        new ApiClient(
            HttpClient.newHttpClient(),
            baseUrl,
            new ClockSkewAdjuster(),
            TestRequestSigner.create());
  }

  @AfterEach
  void stopServer() {
    server.stop(0);
  }

  @Test
  void returnsRecentAccessesFromCurrentSession() throws Exception {
    List<RecentSession> sessions = apiClient.getRecentSessions("PC-01", 5);

    assertEquals(2, sessions.size());
    RecentSession first = sessions.get(0);
    assertEquals("LAB1-PC03", first.machineCode());
    assertEquals("Sala 1", first.lab());
    assertEquals("2026-11-16T14:00:00Z", first.startedAt());
    assertEquals("2026-11-16T15:30:00Z", first.endedAt());
    assertEquals(5400, first.durationSeconds());
    assertEquals("GET", requestMethod);
  }

  @Test
  void returnsEmptyListWhenMachineHasNoOpenSession() throws Exception {
    openSession = false;

    assertTrue(apiClient.getRecentSessions("PC-01", 5).isEmpty());
  }

  @Test
  void keepsAtMostTheRequestedNumberOfAccesses() throws Exception {
    assertEquals(1, apiClient.getRecentSessions("PC-01", 1).size());
  }

  @Test
  void requestIsSignedWithMachineIdentity() throws Exception {
    apiClient.getRecentSessions("PC-01", 5);

    assertTrue(requestHeaders.containsKey("signature-input"));
    assertTrue(requestHeaders.containsKey("signature"));
    assertEquals("PC-01", requestHeaders.get("x-machine-code"));
    assertFalse(requestHeaders.containsKey("x-machine-key"));
  }

  @Test
  void failsClosedWhenNoSignerIsConfigured() {
    ApiClient unsignedClient = new ApiClient(HttpClient.newHttpClient(), baseUrl);

    assertThrows(IllegalStateException.class, () -> unsignedClient.getRecentSessions("PC-01", 5));
  }

  private void handleRequest(HttpExchange exchange) throws IOException {
    requestMethod = exchange.getRequestMethod();
    exchange
        .getRequestHeaders()
        .forEach(
            (name, values) -> requestHeaders.put(name.toLowerCase(Locale.ROOT), values.get(0)));
    exchange.getRequestBody().readAllBytes();

    if (!CURRENT_SESSION_PATH.equals(exchange.getRequestURI().getPath())) {
      exchange.sendResponseHeaders(404, -1);
    } else if (!openSession) {
      exchange.sendResponseHeaders(204, -1);
    } else {
      byte[] body = CURRENT_SESSION_BODY.getBytes(StandardCharsets.UTF_8);
      exchange.getResponseHeaders().set("Content-Type", "application/json");
      exchange.sendResponseHeaders(200, body.length);
      exchange.getResponseBody().write(body);
    }
    exchange.close();
  }
}
