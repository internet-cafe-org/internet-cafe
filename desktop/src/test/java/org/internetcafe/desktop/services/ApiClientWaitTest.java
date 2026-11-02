package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;
import org.junit.jupiter.api.Test;

class ApiClientWaitTest {

  private static final String APPROVED_JSON =
      """
      {"status":"approved",
       "session":{"id":"3f2c0a52","status":"active","started_at":"2026-10-31T15:00:00Z"},
       "user":{"full_name":"Ana Perez","student_code_masked":"2021****34"},
       "recent_accesses":[]}
      """;

  private static final String WAITING_JSON = "{\"status\":\"waiting\"}";

  @Test
  void waitForChallengeSendsMachineCodeAndParsesApprovedResponse() throws Exception {
    AtomicReference<String> machineCode = new AtomicReference<>();
    AtomicReference<String> requestUri = new AtomicReference<>();
    HttpServer server = serve(APPROVED_JSON, machineCode, requestUri);
    try {
      ApiClient client = new ApiClient(HttpClient.newHttpClient(), baseUrl(server));

      ChallengeWaitResponse response = client.waitForChallenge("LAB1-PC03");

      assertEquals("LAB1-PC03", machineCode.get());
      assertEquals(
          "/api/v1/machine/challenges/wait?timeout=" + ApiClient.WAIT_TIMEOUT_SECONDS,
          requestUri.get());
      assertTrue(response.approved());
      assertEquals("Ana Perez", response.displayName());
      assertEquals("2021****34", response.maskedStudentCode());
      assertEquals("active", response.session().status());
    } finally {
      server.stop(0);
    }
  }

  @Test
  void waitForChallengeParsesWaitingResponse() throws Exception {
    HttpServer server = serve(WAITING_JSON, new AtomicReference<>(), new AtomicReference<>());
    try {
      ApiClient client = new ApiClient(HttpClient.newHttpClient(), baseUrl(server));

      ChallengeWaitResponse response = client.waitForChallenge("LAB1-PC03");

      assertFalse(response.approved());
    } finally {
      server.stop(0);
    }
  }

  private static HttpServer serve(
      String json, AtomicReference<String> machineCode, AtomicReference<String> requestUri)
      throws IOException {
    HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext(
        "/",
        exchange -> {
          machineCode.set(exchange.getRequestHeaders().getFirst("X-Machine-Code"));
          requestUri.set(exchange.getRequestURI().toString());
          byte[] body = json.getBytes(StandardCharsets.UTF_8);
          exchange.getResponseHeaders().set("Content-Type", "application/json");
          exchange.sendResponseHeaders(200, body.length);
          exchange.getResponseBody().write(body);
          exchange.close();
        });
    server.start();
    return server;
  }

  private static String baseUrl(HttpServer server) {
    return "http://127.0.0.1:" + server.getAddress().getPort();
  }
}
