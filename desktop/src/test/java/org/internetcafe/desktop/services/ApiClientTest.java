package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.HealthResponse;
import org.internetcafe.desktop.contract.LongPollResponse;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.contract.TemporaryCredentialResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ApiClientTest {
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

  private final Map<String, String> requestBodies = new ConcurrentHashMap<>();
  private final Map<String, String> requestMethods = new ConcurrentHashMap<>();
  private HttpServer server;
  private ApiClient apiClient;
  private String previousApiBaseUrl;

  @BeforeEach
  void startServer() throws IOException {
    previousApiBaseUrl = System.getProperty("api.base.url");
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/", this::handleRequest);
    server.start();
    System.setProperty("api.base.url", "http://127.0.0.1:" + server.getAddress().getPort() + "/");
    apiClient = new ApiClient();
  }

  @AfterEach
  void stopServer() {
    server.stop(0);
    if (previousApiBaseUrl == null) {
      System.clearProperty("api.base.url");
    } else {
      System.setProperty("api.base.url", previousApiBaseUrl);
    }
  }

  @Test
  void contractEndpointsReturnTypedResponsesAndSendExpectedRequests() throws Exception {
    HealthResponse health = apiClient.getHealth();
    assertEquals("ok", health.status());
    assertEquals("backend", health.service());

    var registration =
        apiClient.register(
            new RegistrationRequest("sample-device", "client@example.invalid", "cliente"));
    assertEquals("procesando", registration.estado());
    assertEquals("POST", requestMethods.get("/api/v1/registro"));
    JsonNode registrationBody = OBJECT_MAPPER.readTree(requestBodies.get("/api/v1/registro"));
    assertEquals("sample-device", registrationBody.get("identificacion").asText());
    assertEquals("client@example.invalid", registrationBody.get("correo").asText());

    var enrollment =
        apiClient.enroll(
            new EnrollmentRequest(
                Map.of("kty", "test", "value", "public-key-placeholder"), "signature-placeholder"));
    assertEquals("enrolado", enrollment.estado());
    assertEquals("device-test", enrollment.dispositivoId());
    assertEquals(
        "signature-placeholder",
        OBJECT_MAPPER
            .readTree(requestBodies.get("/api/v1/enroll"))
            .get("prueba_posesion")
            .asText());

    TemporaryCredentialResponse credential = apiClient.getTemporaryCredential("device-test");
    assertEquals("temporary-token", credential.credencialTemporal());
    assertEquals(300, credential.expiracionSegundos());
    assertEquals("device-test", requestBodies.get("credential-device-id"));

    LongPollResponse event = apiClient.longPoll("event 42&next");
    assertEquals("event-42", event.eventoId());
    assertEquals("sesion_autorizada", event.tipo());
    assertEquals(3600, event.datos().get("tiempo_restante"));
    assertEquals("ultimo_evento_id=event+42%26next", requestBodies.get("long-poll-query"));

    assertEquals(Duration.ofSeconds(35), ApiClient.REQUEST_TIMEOUT);
  }

  @Test
  void nonSuccessfulResponseRaisesSanitizedApiException() {
    ApiException exception =
        assertThrows(
            ApiException.class,
            () ->
                apiClient.register(
                    new RegistrationRequest("failure-test", "client@example.invalid", "cliente")));

    assertEquals(409, exception.getStatusCode());
    assertFalse(exception.getMessage().contains("private-response-placeholder"));
  }

  private void handleRequest(HttpExchange exchange) throws IOException {
    String path = exchange.getRequestURI().getPath();
    requestMethods.put(path, exchange.getRequestMethod());
    String requestBody =
        new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
    if (!requestBody.isEmpty()) {
      requestBodies.put(path, requestBody);
    }

    switch (path) {
      case "/healthz" -> respond(exchange, 200, "{\"status\":\"ok\",\"service\":\"backend\"}");
      case "/api/v1/registro" -> {
        if (requestBody.contains("failure-test")) {
          respond(exchange, 409, "{\"error\":\"private-response-placeholder\"}");
        } else {
          respond(exchange, 202, "{\"estado\":\"procesando\",\"mensaje\":\"accepted\"}");
        }
      }
      case "/api/v1/enroll" ->
          respond(exchange, 200, "{\"estado\":\"enrolado\",\"dispositivo_id\":\"device-test\"}");
      case "/api/v1/credencial-provisional" -> {
        requestBodies.put(
            "credential-device-id", exchange.getRequestHeaders().getFirst("X-Device-ID"));
        respond(
            exchange,
            200,
            "{\"credencial_temporal\":\"temporary-token\",\"expiracion_segundos\":300}");
      }
      case "/api/v1/long-poll" -> {
        requestBodies.put("long-poll-query", exchange.getRequestURI().getRawQuery());
        respond(
            exchange,
            200,
            "{\"evento_id\":\"event-42\",\"tipo\":\"sesion_autorizada\","
                + "\"datos\":{\"terminal\":\"PC-05\",\"tiempo_restante\":3600}}");
      }
      default -> respond(exchange, 404, "{}");
    }
  }

  private static void respond(HttpExchange exchange, int statusCode, String body)
      throws IOException {
    byte[] response = body.getBytes(StandardCharsets.UTF_8);
    exchange.getResponseHeaders().set("Content-Type", "application/json");
    exchange.sendResponseHeaders(statusCode, response.length);
    exchange.getResponseBody().write(response);
    exchange.close();
  }
}
