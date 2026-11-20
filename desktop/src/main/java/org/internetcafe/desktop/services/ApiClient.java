package org.internetcafe.desktop.services;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Map;
import java.util.function.Supplier;
import org.internetcafe.desktop.AppConfig;
import org.internetcafe.desktop.contract.ChallengeResponse;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.contract.HealthResponse;
import org.internetcafe.desktop.contract.HeartbeatResponse;
import org.internetcafe.desktop.contract.LongPollResponse;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.contract.RegistrationResponse;
import org.internetcafe.desktop.contract.TemporaryCredentialResponse;
import org.internetcafe.desktop.signing.RequestSigner;
import org.internetcafe.desktop.signing.RequestSigner.SignedRequest;

public class ApiClient {
  static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(35);
  static final int WAIT_TIMEOUT_SECONDS = 25;
  public static final Duration HEARTBEAT_TIMEOUT = Duration.ofSeconds(5);
  private static final String API_PATH = "/api/v1";
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
  private static final String CLOCK_SKEW_CODE = "MACHINE_CLOCK_SKEW";
  private static final SecureRandom SECURE_RANDOM = new SecureRandom();

  private final HttpClient httpClient;
  private final String apiBaseUrl;
  private final ClockSkewAdjuster skewAdjuster;
  private final RequestSigner requestSigner;

  public ApiClient() {
    this(SecureHttpClient.create(REQUEST_TIMEOUT), AppConfig.getApiBaseUrl(), (RequestSigner) null);
  }

  public ApiClient(RequestSigner requestSigner) {
    this(SecureHttpClient.create(REQUEST_TIMEOUT), AppConfig.getApiBaseUrl(), requestSigner);
  }

  private ApiClient(HttpClient httpClient, String apiBaseUrl, RequestSigner requestSigner) {
    this(httpClient, apiBaseUrl, new ClockSkewAdjuster(), requestSigner);
  }

  ApiClient(HttpClient httpClient, String apiBaseUrl) {
    this(httpClient, apiBaseUrl, new ClockSkewAdjuster(), null);
  }

  ApiClient(HttpClient httpClient, String apiBaseUrl, ClockSkewAdjuster skewAdjuster) {
    this(httpClient, apiBaseUrl, skewAdjuster, null);
  }

  ApiClient(
      HttpClient httpClient,
      String apiBaseUrl,
      ClockSkewAdjuster skewAdjuster,
      RequestSigner requestSigner) {
    this.httpClient = httpClient;
    this.apiBaseUrl = apiBaseUrl;
    this.skewAdjuster = skewAdjuster;
    this.requestSigner = requestSigner;
  }

  /** Returns the clock-skew adjuster so callers can read the current offset when signing. */
  public ClockSkewAdjuster skewAdjuster() {
    return skewAdjuster;
  }

  public HealthResponse getHealth() throws IOException, InterruptedException {
    return get("/healthz", HealthResponse.class);
  }

  public RegistrationResponse register(RegistrationRequest request)
      throws IOException, InterruptedException {
    return post("/registro", request, RegistrationResponse.class);
  }

  public EnrollmentResponse enroll(EnrollmentRequest request)
      throws IOException, InterruptedException {
    return post("/machine/enroll", request, EnrollmentResponse.class);
  }

  public TemporaryCredentialResponse getTemporaryCredential(String deviceId)
      throws IOException, InterruptedException {
    HttpRequest request =
        requestBuilder(API_PATH + "/credencial-provisional")
            .header("X-Device-ID", deviceId)
            .GET()
            .build();
    return send(request, TemporaryCredentialResponse.class);
  }

  public ChallengeResponse createChallenge(String machineCode)
      throws IOException, InterruptedException {
    return sendMachineRequest(
        "POST", API_PATH + "/machine/challenges", machineCode, null, null, ChallengeResponse.class);
  }

  /**
   * Waits (long-poll) until a student claims the machine's QR challenge or the server timeout
   * elapses. The status of the response is either "approved" or "waiting".
   */
  public ChallengeWaitResponse waitForChallenge(String machineCode)
      throws IOException, InterruptedException {
    return sendMachineRequest(
        "GET",
        API_PATH + "/machine/challenges/wait?timeout=" + WAIT_TIMEOUT_SECONDS,
        machineCode,
        null,
        null,
        ChallengeWaitResponse.class);
  }

  /**
   * Sends the machine heartbeat (every 60 s). {@code sessionId} is the session the machine believes
   * is open, or {@code null} when it has none. The short timeout keeps remote-close detection under
   * 65 s.
   */
  public HeartbeatResponse sendHeartbeat(String machineCode, String sessionId)
      throws IOException, InterruptedException {
    String json =
        sessionId == null || sessionId.isBlank()
            ? "{}"
            : OBJECT_MAPPER.writeValueAsString(Map.of("session_id", sessionId));
    return sendMachineRequest(
        "POST",
        API_PATH + "/machine/heartbeat",
        machineCode,
        json.getBytes(StandardCharsets.UTF_8),
        HEARTBEAT_TIMEOUT,
        HeartbeatResponse.class);
  }

  /** Closes the machine's open session (reason {@code user_logout_pc}). */
  public void endCurrentSession(String machineCode) throws IOException, InterruptedException {
    sendMachineRequest(
        "POST",
        API_PATH + "/machine/sessions/current/end",
        machineCode,
        "{\"reason\":\"user_logout_pc\"}".getBytes(StandardCharsets.UTF_8),
        null,
        JsonNode.class);
  }

  public LongPollResponse longPoll(String lastEventId) throws IOException, InterruptedException {
    String path = API_PATH + "/long-poll";
    if (lastEventId != null && !lastEventId.isBlank()) {
      path += "?ultimo_evento_id=" + URLEncoder.encode(lastEventId, StandardCharsets.UTF_8);
    }
    return get(path, LongPollResponse.class);
  }

  private <T> T get(String path, Class<T> responseType) throws IOException, InterruptedException {
    return send(requestBuilder(path).GET().build(), responseType);
  }

  private <T> T post(String path, Object body, Class<T> responseType)
      throws IOException, InterruptedException {
    String json = OBJECT_MAPPER.writeValueAsString(body);
    HttpRequest request =
        requestBuilder(API_PATH + path)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
            .build();
    return send(request, responseType);
  }

  private HttpRequest.Builder requestBuilder(String path) {
    return HttpRequest.newBuilder(URI.create(apiBaseUrl + path))
        .timeout(REQUEST_TIMEOUT)
        .header("Accept", "application/json");
  }

  private <T> T sendMachineRequest(
      String method,
      String path,
      String machineCode,
      byte[] body,
      Duration timeout,
      Class<T> responseType)
      throws IOException, InterruptedException {
    if (requestSigner == null) {
      throw new IllegalStateException("Machine request signing is not configured");
    }
    Supplier<HttpRequest> requestFactory =
        () -> {
          try {
            return buildSignedRequest(method, path, machineCode, body, timeout);
          } catch (GeneralSecurityException exception) {
            throw new RequestSigningException(exception);
          }
        };
    try {
      return send(requestFactory, responseType, true);
    } catch (RequestSigningException exception) {
      throw new IOException("Unable to sign machine request", exception.getCause());
    }
  }

  private HttpRequest buildSignedRequest(
      String method, String path, String machineCode, byte[] body, Duration timeout)
      throws GeneralSecurityException {
    byte[] nonceBytes = new byte[16];
    SECURE_RANDOM.nextBytes(nonceBytes);
    String nonce = Base64.getUrlEncoder().withoutPadding().encodeToString(nonceBytes);
    String targetUri = apiBaseUrl + path;
    SignedRequest signed =
        requestSigner.sign(
            method,
            targetUri,
            body,
            Instant.now().plusMillis(skewAdjuster.offsetMillis()).getEpochSecond(),
            nonce);
    HttpRequest.Builder builder =
        requestBuilder(path)
            .header("X-Machine-Code", machineCode)
            .header("Signature-Input", signed.signatureInput())
            .header("Signature", signed.signatureHeader());
    if (signed.contentDigest() != null) {
      builder.header("Content-Digest", signed.contentDigest());
    }
    if (timeout != null) {
      builder.timeout(timeout);
    }
    if (body == null) {
      if ("GET".equals(method)) {
        builder.GET();
      } else {
        builder.POST(HttpRequest.BodyPublishers.noBody());
      }
    } else {
      builder
          .header("Content-Type", "application/json")
          .method(method, HttpRequest.BodyPublishers.ofByteArray(body));
    }
    return builder.build();
  }

  private <T> T send(HttpRequest request, Class<T> responseType)
      throws IOException, InterruptedException {
    return send(() -> request, responseType, true);
  }

  /**
   * Sends {@code request} and deserialises the response body.
   *
   * <p>When {@code retryOnSkew} is {@code true} and the server responds with HTTP 401 containing
   * {@code MACHINE_CLOCK_SKEW}, the {@code Date} header is used to correct the local clock offset
   * (via {@link ClockSkewAdjuster}) and the request is retried exactly once. The corrected offset
   * is then available via {@link #skewAdjuster()} for subsequent signed requests (DSK-12).
   *
   * @param retryOnSkew {@code false} on the retry itself to prevent infinite loops
   */
  private <T> T send(
      Supplier<HttpRequest> requestFactory, Class<T> responseType, boolean retryOnSkew)
      throws IOException, InterruptedException {
    HttpRequest request = requestFactory.get();
    HttpResponse<String> response =
        httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

    if (response.statusCode() < 200 || response.statusCode() >= 300) {
      if (retryOnSkew && response.statusCode() == 401 && isClockSkewError(response.body())) {
        String dateHeader = response.headers().firstValue("Date").orElse(null);
        if (skewAdjuster.applyFromDateHeader(dateHeader)) {
          return send(requestFactory, responseType, false);
        }
        // Date header missing or unparseable — surface with the header attached
        throw new ApiException(response.statusCode(), dateHeader);
      }
      throw new ApiException(response.statusCode());
    }

    return OBJECT_MAPPER.readValue(response.body(), responseType);
  }

  private static final class RequestSigningException extends RuntimeException {
    private RequestSigningException(GeneralSecurityException cause) {
      super(cause);
    }
  }

  /**
   * Returns {@code true} when the response body signals a clock-skew rejection. Checks for the
   * literal string {@code MACHINE_CLOCK_SKEW} so it works with both RFC 9457 problem details and
   * plain JSON error objects.
   */
  static boolean isClockSkewError(String body) {
    return body != null && body.contains(CLOCK_SKEW_CODE);
  }
}
