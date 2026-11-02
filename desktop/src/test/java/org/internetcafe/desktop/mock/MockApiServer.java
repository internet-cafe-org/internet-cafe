package org.internetcafe.desktop.mock;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;

/**
 * API simulada local (DSK-07) para probar el escritorio sin el backend real.
 *
 * <p>Responde con los valores de ejemplo de {@code Backend/contrato.md} (registro, enroll,
 * credencial-provisional y long-poll) y con la forma real del backend para {@code /healthz} y
 * {@code POST /api/v1/machine/challenges}. Solo escucha en 127.0.0.1 y no escribe cuerpos,
 * cabeceras ni query strings en el log.
 *
 * <p>Los casos de error (404, 405 y 400 por cabecera faltante) son convenciones del simulador: el
 * contrato v0.1 solo define las respuestas exitosas.
 */
public final class MockApiServer implements AutoCloseable {
  static final int DEFAULT_PORT = 8000;
  private static final int CHALLENGE_TTL_SECONDS = 60;
  private static final int ROTATE_AFTER_SECONDS = 45;

  private static final String HEALTH = "{\"status\":\"ok\",\"service\":\"backend\"}";
  private static final String REGISTRO =
      "{\"estado\":\"procesando\","
          + "\"mensaje\":\"Registro aceptado para procesamiento en segundo plano\"}";
  private static final String ENROLL = "{\"estado\":\"enrolado\",\"dispositivo_id\":\"dev-98765\"}";
  private static final String CREDENCIAL =
      "{\"credencial_temporal\":\"temp-token-xyz-789\",\"expiracion_segundos\":300}";
  private static final String LONG_POLL =
      "{\"evento_id\":\"evt-456\",\"tipo\":\"sesion_autorizada\","
          + "\"datos\":{\"terminal\":\"PC-05\",\"tiempo_restante\":3600}}";

  private static final Reply NOT_FOUND = new Reply(404, "{}");
  private static final Reply METHOD_NOT_ALLOWED = new Reply(405, "{}");
  private static final Reply BAD_REQUEST = new Reply(400, "{}");

  private record Reply(int status, String body) {}

  private final HttpServer server;
  private final long longPollDelayMillis;

  public MockApiServer(int port, long longPollDelayMillis) throws IOException {
    this.longPollDelayMillis = longPollDelayMillis;
    this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
    this.server.createContext("/", this::handle);
  }

  /**
   * Puerto con MOCK_API_PORT (por defecto 8000) y espera del long-poll en milisegundos con
   * MOCK_LONG_POLL_DELAY_MS (por defecto 0).
   */
  public static void main(String[] args) throws IOException {
    MockApiServer mock =
        new MockApiServer(
            readEnvInt("MOCK_API_PORT", DEFAULT_PORT), readEnvInt("MOCK_LONG_POLL_DELAY_MS", 0));
    mock.start();
    Runtime.getRuntime().addShutdownHook(new Thread(mock::close));
    System.out.println("API simulada escuchando en " + mock.baseUrl() + " (Ctrl+C para detener)");
  }

  public void start() {
    server.start();
  }

  public String baseUrl() {
    return "http://127.0.0.1:" + server.getAddress().getPort();
  }

  @Override
  public void close() {
    server.stop(0);
  }

  private void handle(HttpExchange exchange) throws IOException {
    try (exchange) {
      exchange.getRequestBody().readAllBytes();
      Reply reply = route(exchange);
      byte[] body = reply.body().getBytes(StandardCharsets.UTF_8);
      exchange.getResponseHeaders().set("Content-Type", "application/json");
      exchange.sendResponseHeaders(reply.status(), body.length);
      exchange.getResponseBody().write(body);
      System.out.println(
          exchange.getRequestMethod()
              + " "
              + exchange.getRequestURI().getPath()
              + " -> "
              + reply.status());
    }
  }

  private Reply route(HttpExchange exchange) {
    return switch (exchange.getRequestURI().getPath()) {
      case "/healthz" -> is(exchange, "GET") ? new Reply(200, HEALTH) : METHOD_NOT_ALLOWED;
      case "/api/v1/registro" ->
          is(exchange, "POST") ? new Reply(202, REGISTRO) : METHOD_NOT_ALLOWED;
      case "/api/v1/enroll" -> is(exchange, "POST") ? new Reply(200, ENROLL) : METHOD_NOT_ALLOWED;
      case "/api/v1/credencial-provisional" ->
          !is(exchange, "GET")
              ? METHOD_NOT_ALLOWED
              : hasHeader(exchange, "X-Device-ID") ? new Reply(200, CREDENCIAL) : BAD_REQUEST;
      case "/api/v1/long-poll" -> is(exchange, "GET") ? longPoll() : METHOD_NOT_ALLOWED;
      case "/api/v1/machine/challenges" ->
          !is(exchange, "POST")
              ? METHOD_NOT_ALLOWED
              : hasHeader(exchange, "X-Machine-Code") ? challenge() : BAD_REQUEST;
      default -> NOT_FOUND;
    };
  }

  private Reply longPoll() {
    if (longPollDelayMillis > 0) {
      try {
        Thread.sleep(longPollDelayMillis);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
    }
    return new Reply(200, LONG_POLL);
  }

  private static Reply challenge() {
    String body =
        "{\"challenge_id\":\""
            + UUID.randomUUID()
            + "\",\"qr_url\":\"https://front.example.invalid/s#mock-token\","
            + "\"expires_at\":\""
            + Instant.now().plusSeconds(CHALLENGE_TTL_SECONDS)
            + "\",\"rotate_after_s\":"
            + ROTATE_AFTER_SECONDS
            + "}";
    return new Reply(201, body);
  }

  private static boolean is(HttpExchange exchange, String method) {
    return method.equals(exchange.getRequestMethod());
  }

  private static boolean hasHeader(HttpExchange exchange, String name) {
    String value = exchange.getRequestHeaders().getFirst(name);
    return value != null && !value.isBlank();
  }

  private static int readEnvInt(String name, int fallback) {
    String value = System.getenv(name);
    return value == null || value.isBlank() ? fallback : Integer.parseInt(value.trim());
  }
}
