package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.time.Duration;
import java.util.Base64;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.internetcafe.desktop.contract.ChallengeResponse;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.HealthResponse;
import org.internetcafe.desktop.contract.HeartbeatResponse;
import org.internetcafe.desktop.contract.LongPollResponse;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.contract.TemporaryCredentialResponse;
import org.internetcafe.desktop.identity.PublicJwk;
import org.internetcafe.desktop.signing.RequestSigner;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class ApiClientTest {
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

  private final Map<String, String> requestBodies = new ConcurrentHashMap<>();
  private final Map<String, String> requestMethods = new ConcurrentHashMap<>();
  private final Map<String, String> requestUris = new ConcurrentHashMap<>();
  private final Map<String, Map<String, String>> requestHeaders = new ConcurrentHashMap<>();
  private HttpServer server;
  private ApiClient apiClient;
  private RequestSigner requestSigner;
  private ECPublicKey publicKey;
  private final Set<String> signedNonces = new HashSet<>();
  private final AtomicInteger skewChallengeCount = new AtomicInteger();
  private volatile boolean skewChallengeRetry;
  private String firstSkewSignatureInput;
  private String previousApiBaseUrl;

  @BeforeEach
  void startServer() throws Exception {
    previousApiBaseUrl = System.getProperty("api.base.url");
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/", this::handleRequest);
    server.start();
    System.setProperty("api.base.url", "http://127.0.0.1:" + server.getAddress().getPort() + "/");
    KeyPairHolder keyPairHolder = createTestKeyPair();
    requestSigner = keyPairHolder.requestSigner();
    publicKey = keyPairHolder.publicKey();
    apiClient =
        new ApiClient(
            HttpClient.newHttpClient(),
            "http://127.0.0.1:" + server.getAddress().getPort(),
            new ClockSkewAdjuster(),
            requestSigner);
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
                "enrollment-code-placeholder",
                new PublicJwk("EC", "P-256", "A".repeat(43), "A".repeat(43)),
                "proof-placeholder"));
    assertEquals("machine-test", enrollment.machineId());
    assertEquals("LAB1-PC03", enrollment.code());
    assertEquals("Sala 1", enrollment.lab());
    assertEquals("kiosk", enrollment.mode());
    assertEquals("keyid-placeholder", enrollment.keyid());
    assertEquals("credential-placeholder", enrollment.provisionalCredential());
    assertEquals("POST", requestMethods.get("/api/v1/machine/enroll"));
    JsonNode enrollmentBody = OBJECT_MAPPER.readTree(requestBodies.get("/api/v1/machine/enroll"));
    assertEquals("enrollment-code-placeholder", enrollmentBody.get("enrollment_code").asText());
    assertEquals("EC", enrollmentBody.get("jwk").get("kty").asText());
    assertFalse(enrollmentBody.get("jwk").has("d"));
    assertEquals("proof-placeholder", enrollmentBody.get("proof").asText());

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
  void createChallengeReturnsTypedResponse() throws Exception {
    ChallengeResponse challenge = apiClient.createChallenge("PC-01");
    assertEquals("challenge-test", challenge.challengeId());
    assertEquals("https://front.example.invalid/s#sample", challenge.qrUrl());
    assertEquals(45, challenge.rotateAfterSeconds());
    assertEquals("PC-01", requestBodies.get("machine-code"));
    assertEquals("POST", requestMethods.get("/api/v1/machine/challenges"));
  }

  @Test
  void everyMachineRequestIsSignedAndVerifiable() throws Exception {
    apiClient.createChallenge("PC-01");
    apiClient.waitForChallenge("PC-01");
    HeartbeatResponse heartbeat = apiClient.sendHeartbeat("PC-01", null);
    assertEquals("none", heartbeat.sessionStatus());
    apiClient.endCurrentSession("PC-01");

    assertValidSignature("/api/v1/machine/challenges", "POST", null);
    assertValidSignature("/api/v1/machine/challenges/wait", "GET", null);
    assertValidSignature("/api/v1/machine/heartbeat", "POST", "{}");
    assertValidSignature(
        "/api/v1/machine/sessions/current/end", "POST", "{\"reason\":\"user_logout_pc\"}");
    assertEquals(
        "/api/v1/machine/challenges/wait?timeout=" + ApiClient.WAIT_TIMEOUT_SECONDS,
        requestUris.get("/api/v1/machine/challenges/wait"));
  }

  @Test
  void machineRequestsFailClosedWhenNoSignerIsConfigured() {
    ApiClient unsignedClient =
        new ApiClient(
            HttpClient.newHttpClient(), "http://127.0.0.1:" + server.getAddress().getPort());

    assertThrows(IllegalStateException.class, () -> unsignedClient.createChallenge("PC-01"));
  }

  @Test
  void clockSkewRetrySignsTheRequestAgainWithANewNonce() throws Exception {
    skewChallengeRetry = true;

    apiClient.createChallenge("PC-01");

    assertEquals(2, skewChallengeCount.get());
    assertNotEquals(
        firstSkewSignatureInput,
        requestHeaders.get("/api/v1/machine/challenges").get("signature-input"));
    assertValidSignature("/api/v1/machine/challenges", "POST", null);
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
    requestUris.put(path, exchange.getRequestURI().toString());
    Map<String, String> headers = new ConcurrentHashMap<>();
    exchange
        .getRequestHeaders()
        .forEach(
            (name, values) -> headers.put(name.toLowerCase(java.util.Locale.ROOT), values.get(0)));
    requestHeaders.put(path, headers);
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
      case "/api/v1/machine/enroll" ->
          respond(
              exchange,
              201,
              "{\"machine_id\":\"machine-test\",\"code\":\"LAB1-PC03\","
                  + "\"lab\":\"Sala 1\",\"mode\":\"kiosk\","
                  + "\"keyid\":\"keyid-placeholder\","
                  + "\"provisional_credential\":\"credential-placeholder\"}");
      case "/api/v1/credencial-provisional" -> {
        requestBodies.put(
            "credential-device-id", exchange.getRequestHeaders().getFirst("X-Device-ID"));
        respond(
            exchange,
            200,
            "{\"credencial_temporal\":\"temporary-token\",\"expiracion_segundos\":300}");
      }
      case "/api/v1/machine/challenges" -> {
        requestBodies.put("machine-code", exchange.getRequestHeaders().getFirst("X-Machine-Code"));
        if (skewChallengeRetry && skewChallengeCount.incrementAndGet() == 1) {
          firstSkewSignatureInput = exchange.getRequestHeaders().getFirst("Signature-Input");
          respond(exchange, 401, "{\"code\":\"MACHINE_CLOCK_SKEW\"}");
          return;
        }
        respond(
            exchange,
            201,
            "{\"challenge_id\":\"challenge-test\","
                + "\"qr_url\":\"https://front.example.invalid/s#sample\","
                + "\"expires_at\":\"2026-10-19T14:05:00Z\","
                + "\"rotate_after_s\":45}");
      }
      case "/api/v1/machine/challenges/wait" -> respond(exchange, 200, "{\"status\":\"waiting\"}");
      case "/api/v1/machine/heartbeat" -> respond(exchange, 200, "{\"session_status\":\"none\"}");
      case "/api/v1/machine/sessions/current/end" -> respond(exchange, 200, "{}");
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

  private void assertValidSignature(String path, String method, String body) throws Exception {
    Map<String, String> headers = requestHeaders.get(path);
    assertTrue(headers.containsKey("signature-input"), path + " must include Signature-Input");
    assertTrue(headers.containsKey("signature"), path + " must include Signature");
    assertEquals("PC-01", headers.get("x-machine-code"));
    assertFalse(headers.containsKey("x-machine-key"));

    String contentDigest = headers.get("content-digest");
    if (body == null) {
      assertNull(contentDigest);
    } else {
      assertEquals(
          RequestSigner.contentDigest(body.getBytes(StandardCharsets.UTF_8)), contentDigest);
    }

    String signatureInput = headers.get("signature-input");
    String signatureParams = signatureInput.substring("sig1=".length());
    assertTrue(signatureParams.contains(";keyid=\"" + requestSigner.keyId() + "\""));
    int nonceStart = signatureParams.indexOf(";nonce=\"");
    assertTrue(nonceStart >= 0);
    int nonceValueStart = nonceStart + ";nonce=\"".length();
    int nonceEnd = signatureParams.indexOf('"', nonceValueStart);
    assertTrue(nonceEnd > nonceValueStart);
    assertTrue(signedNonces.add(signatureParams.substring(nonceValueStart, nonceEnd)));
    String targetUri = baseUrl(server) + requestUris.get(path);
    StringBuilder signatureBase = new StringBuilder();
    signatureBase.append("\"@method\": ").append(method).append('\n');
    signatureBase.append("\"@target-uri\": ").append(targetUri).append('\n');
    if (contentDigest != null) {
      signatureBase.append("\"content-digest\": ").append(contentDigest).append('\n');
    }
    signatureBase.append("\"@signature-params\": ").append(signatureParams);

    String signatureHeader = headers.get("signature");
    byte[] rawSignature =
        Base64.getDecoder()
            .decode(signatureHeader.substring("sig1=:".length(), signatureHeader.length() - 1));
    Signature verifier = Signature.getInstance("SHA256withECDSA");
    verifier.initVerify(publicKey);
    verifier.update(signatureBase.toString().getBytes(StandardCharsets.UTF_8));
    assertTrue(verifier.verify(rawToDer(rawSignature)), path + " signature must verify");
  }

  private KeyPairHolder createTestKeyPair() throws Exception {
    var generator = java.security.KeyPairGenerator.getInstance("EC");
    generator.initialize(new java.security.spec.ECGenParameterSpec("secp256r1"));
    var keyPair = generator.generateKeyPair();
    ECPublicKey publicKey = (ECPublicKey) keyPair.getPublic();
    return new KeyPairHolder(
        new RequestSigner(keyPair.getPrivate(), PublicJwk.from(publicKey)), publicKey);
  }

  private static String baseUrl(HttpServer server) {
    return "http://127.0.0.1:" + server.getAddress().getPort();
  }

  private static byte[] rawToDer(byte[] raw) {
    byte[] r = derInteger(raw, 0);
    byte[] s = derInteger(raw, 32);
    byte[] der = new byte[2 + r.length + s.length];
    der[0] = 0x30;
    der[1] = (byte) (r.length + s.length);
    System.arraycopy(r, 0, der, 2, r.length);
    System.arraycopy(s, 0, der, 2 + r.length, s.length);
    return der;
  }

  private static byte[] derInteger(byte[] raw, int offset) {
    int start = offset;
    while (start < offset + 31 && raw[start] == 0) {
      start++;
    }
    boolean needsPadding = (raw[start] & 0x80) != 0;
    int length = offset + 32 - start + (needsPadding ? 1 : 0);
    byte[] integer = new byte[length + 2];
    integer[0] = 0x02;
    integer[1] = (byte) length;
    System.arraycopy(raw, start, integer, needsPadding ? 3 : 2, offset + 32 - start);
    return integer;
  }

  private record KeyPairHolder(RequestSigner requestSigner, ECPublicKey publicKey) {}
}
