package org.internetcafe.desktop.mock;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Map;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.RegistrationRequest;
import org.internetcafe.desktop.services.ApiClient;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** Camino feliz del ApiClient real contra la API simulada (DSK-07). */
class MockApiServerTest {
  private MockApiServer mock;
  private String previousApiBaseUrl;

  @BeforeEach
  void startMock() throws IOException {
    previousApiBaseUrl = System.getProperty("api.base.url");
    mock = new MockApiServer(0, 0);
    mock.start();
    System.setProperty("api.base.url", mock.baseUrl());
  }

  @AfterEach
  void stopMock() {
    mock.close();
    if (previousApiBaseUrl == null) {
      System.clearProperty("api.base.url");
    } else {
      System.setProperty("api.base.url", previousApiBaseUrl);
    }
  }

  @Test
  void apiClientHappyPathAgainstMock() throws Exception {
    ApiClient client = new ApiClient();

    var health = client.getHealth();
    assertEquals("ok", health.status());
    assertEquals("backend", health.service());

    var registration =
        client.register(new RegistrationRequest("sample-id", "client@example.invalid", "cliente"));
    assertEquals("procesando", registration.estado());

    var enrollment =
        client.enroll(new EnrollmentRequest(Map.of("kty", "EC"), "signature-placeholder"));
    assertEquals("enrolado", enrollment.estado());
    assertEquals("dev-98765", enrollment.dispositivoId());

    var credential = client.getTemporaryCredential("dev-98765");
    assertEquals("temp-token-xyz-789", credential.credencialTemporal());
    assertEquals(300, credential.expiracionSegundos());

    var event = client.longPoll("evt-455");
    assertEquals("evt-456", event.eventoId());
    assertEquals("sesion_autorizada", event.tipo());
    assertEquals("PC-05", event.datos().get("terminal"));

    var challenge = client.createChallenge("PC-01");
    assertFalse(challenge.challengeId().isBlank());
    assertEquals(45, challenge.rotateAfterSeconds());
  }

  @Test
  void registroRespondsWith202AsInContract() throws Exception {
    HttpRequest request =
        HttpRequest.newBuilder(URI.create(mock.baseUrl() + "/api/v1/registro"))
            .POST(HttpRequest.BodyPublishers.ofString("{}"))
            .build();

    HttpResponse<String> response =
        HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());

    assertEquals(202, response.statusCode());
  }
}
