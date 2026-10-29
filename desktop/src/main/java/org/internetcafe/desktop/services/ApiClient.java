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
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.contract.HealthResponse;
import org.internetcafe.desktop.contract.LongPollResponse;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.contract.RegistrationResponse;
import org.internetcafe.desktop.contract.TemporaryCredentialResponse;

public class ApiClient {
  static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(35);
  private static final String API_PATH = "/api/v1";
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

  private final HttpClient httpClient;
  private final String apiBaseUrl;

  public ApiClient() {
    this(
        HttpClient.newBuilder().connectTimeout(REQUEST_TIMEOUT).build(), AppConfig.getApiBaseUrl());
  }

  ApiClient(HttpClient httpClient, String apiBaseUrl) {
    this.httpClient = httpClient;
    this.apiBaseUrl = apiBaseUrl;
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
    HttpResponse<String> response =
        httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    if (response.statusCode() < 200 || response.statusCode() >= 300) {
      throw new ApiException(response.statusCode());
    }
    return OBJECT_MAPPER.readValue(response.body(), responseType);
  }
}
