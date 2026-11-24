package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
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
import java.util.Base64;
import java.util.concurrent.atomic.AtomicReference;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.identity.EnrollmentStore;
import org.internetcafe.desktop.identity.MachineIdentity;
import org.internetcafe.desktop.identity.MachineIdentityStore;
import org.internetcafe.desktop.identity.ProtectedFile;
import org.internetcafe.desktop.identity.SecretProtector;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class EnrollmentServiceTest {
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
  private static final SecretProtector TEST_PROTECTOR =
      new SecretProtector() {
        @Override
        public byte[] protect(byte[] plaintext) {
          return transform(plaintext);
        }

        @Override
        public byte[] unprotect(byte[] ciphertext) {
          return transform(ciphertext);
        }

        private byte[] transform(byte[] input) {
          byte[] result = input.clone();
          for (int index = 0; index < result.length; index++) {
            result[index] ^= 0x5a;
          }
          return result;
        }
      };

  @TempDir java.nio.file.Path temporaryDirectory;

  private final AtomicReference<String> requestBody = new AtomicReference<>();
  private HttpServer server;
  private volatile int responseStatus;
  private volatile String responseKeyid;
  private EnrollmentService service;
  private MachineIdentity identity;
  private EnrollmentStore enrollmentStore;

  @BeforeEach
  void setUp() throws Exception {
    responseStatus = 201;
    char[] password = "test-only-identity-password".toCharArray();
    MachineIdentityStore identityStore =
        new MachineIdentityStore(temporaryDirectory.resolve("identity"), password);
    identity = identityStore.loadOrCreate();
    responseKeyid = identity.thumbprint();
    server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    server.createContext("/api/v1/machine/enroll", this::handleEnrollment);
    server.start();
    enrollmentStore =
        new EnrollmentStore(
            new ProtectedFile(temporaryDirectory.resolve("enrollment.bin"), TEST_PROTECTOR));
    ApiClient apiClient =
        new ApiClient(
            HttpClient.newHttpClient(), "http://127.0.0.1:" + server.getAddress().getPort());
    service = new EnrollmentService(apiClient, identityStore, enrollmentStore);
  }

  @AfterEach
  void tearDown() {
    server.stop(0);
  }

  @Test
  void signsCodeSendsPublicJwkAndPersistsSuccessfulEnrollment() throws Exception {
    EnrollmentResponse response = service.enroll("one-time-code-123");

    assertEquals("machine-test", response.machineId());
    assertEquals("LAB1-PC03", response.code());
    assertEquals("Sala 1", response.lab());
    assertEquals("kiosk", response.mode());
    assertEquals(identity.thumbprint(), response.keyid());
    assertEquals(response, enrollmentStore.load());

    JsonNode request = OBJECT_MAPPER.readTree(requestBody.get());
    assertEquals("one-time-code-123", request.get("enrollment_code").asText());
    assertEquals("EC", request.get("jwk").get("kty").asText());
    assertEquals("P-256", request.get("jwk").get("crv").asText());
    assertFalse(request.get("jwk").has("d"));

    byte[] proof = Base64.getUrlDecoder().decode(request.get("proof").asText());
    Signature verifier = Signature.getInstance("SHA256withECDSAinP1363Format");
    verifier.initVerify(identity.publicKey());
    verifier.update("one-time-code-123".getBytes(StandardCharsets.UTF_8));
    assertEquals(64, proof.length);
    assertTrue(verifier.verify(proof));
  }

  @Test
  void rejectsInvalidCodeBeforeSendingRequest() {
    assertThrows(IllegalArgumentException.class, () -> service.enroll("short"));
    assertTrue(requestBody.get() == null);
  }

  @Test
  void surfacesAnInvalidOrExpiredCodeResponseWithoutStoringCredentials() {
    responseStatus = 401;

    ApiException exception =
        assertThrows(ApiException.class, () -> service.enroll("one-time-code-123"));

    assertEquals(401, exception.getStatusCode());
    assertThrows(IOException.class, enrollmentStore::load);
  }

  @Test
  void rejectsAndDoesNotPersistAResponseBoundToAnotherKey() {
    responseKeyid = "different-keyid";

    assertThrows(EnrollmentCommitException.class, () -> service.enroll("one-time-code-123"));
    assertThrows(IOException.class, enrollmentStore::load);
  }

  private void handleEnrollment(HttpExchange exchange) throws IOException {
    requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
    byte[] body;
    if (responseStatus == 201) {
      body =
          ("{\"machine_id\":\"machine-test\",\"code\":\"LAB1-PC03\","
                  + "\"lab\":\"Sala 1\",\"mode\":\"kiosk\","
                  + "\"keyid\":\""
                  + responseKeyid
                  + "\"}")
              .getBytes(StandardCharsets.UTF_8);
    } else {
      body = "{\"code\":\"ENROLLMENT_CODE_INVALID\"}".getBytes(StandardCharsets.UTF_8);
    }
    exchange.getResponseHeaders().set("Content-Type", "application/json");
    exchange.sendResponseHeaders(responseStatus, body.length);
    exchange.getResponseBody().write(body);
    exchange.close();
  }
}
