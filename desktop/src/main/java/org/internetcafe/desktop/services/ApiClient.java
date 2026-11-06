package org.internetcafe.desktop.services;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import org.internetcafe.desktop.AppConfig;
import org.internetcafe.desktop.contract.ChallengeResponse;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.contract.HealthResponse;
import org.internetcafe.desktop.contract.LongPollResponse;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.contract.RegistrationResponse;
import org.internetcafe.desktop.contract.TemporaryCredentialResponse;

public class ApiClient {
  static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(35);
  static final int WAIT_TIMEOUT_SECONDS = 25;
  private static final String API_PATH = "/api/v1";
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
  private static final String CLOCK_SKEW_CODE = "MACHINE_CLOCK_SKEW";

  private final HttpClient httpClient;
  private final String apiBaseUrl;
  private final ClockSkewAdjuster skewAdjuster;

  public ApiClient() {
    this(SecureHttpClient.create(REQUEST_TIMEOUT), AppConfig.getApiBaseUrl());
  }

  ApiClient(HttpClient httpClient, String apiBaseUrl) {
    this(httpClient, apiBaseUrl, new ClockSkewAdjuster());
  }

  ApiClient(HttpClient httpClient, String apiBaseUrl, ClockSkewAdjuster skewAdjuster) {
    this.httpClient = httpClient;
    this.apiBaseUrl = apiBaseUrl;
    this.skewAdjuster = skewAdjuster;
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
    return post("/enroll", request, EnrollmentResponse.class);
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
    HttpRequest request =
        requestBuilder(API_PATH + "/machine/challenges")
            .header("X-Machine-Code", machineCode)
            .POST(HttpRequest.BodyPublishers.noBody())
            .build();
    return send(request, ChallengeResponse.class);
  }

  /**
   * Waits (long-poll) until a student claims the machine's QR challenge or the server timeout
   * elapses. The status of the response is either "approved" or "waiting".
   */
  public ChallengeWaitResponse waitForChallenge(String machineCode)
      throws IOException, InterruptedException {
    HttpRequest request =
        requestBuilder(API_PATH + "/machine/challenges/wait?timeout=" + WAIT_TIMEOUT_SECONDS)
            .header("X-Machine-Code", machineCode)
            .GET()
            .build();
    return send(request, ChallengeWaitResponse.class);
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

  private <T> T send(HttpRequest request, Class<T> responseType)
      throws IOException, InterruptedException {
    return send(request, responseType, true);
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
  private <T> T send(HttpRequest request, Class<T> responseType, boolean retryOnSkew)
      throws IOException, InterruptedException {
    HttpResponse<String> response =
        httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));

    if (response.statusCode() < 200 || response.statusCode() >= 300) {
      if (retryOnSkew
          && response.statusCode() == 401
          && isClockSkewError(response.body())) {
        String dateHeader = response.headers().firstValue("Date").orElse(null);
        if (skewAdjuster.applyFromDateHeader(dateHeader)) {
          return send(request, responseType, false);
        }
        // Date header missing or unparseable — surface with the header attached
        throw new ApiException(response.statusCode(), dateHeader);
      }
      throw new ApiException(response.statusCode());
    }

    return OBJECT_MAPPER.readValue(response.body(), responseType);
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
