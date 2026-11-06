package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.Proxy;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Set;
import java.util.TreeSet;
import org.junit.jupiter.api.Test;

class SecureHttpClientTest {

  private static final Set<String> EXPECTED_SHA256 =
      Set.of(
          "96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6",
          "69729b8e15a86efc177a57afb7171dfc64add28c2fca8cf1507e34453ccb1470",
          "d947432abde7b7fa90fc2e6b59101b1280e0e1c7e4e40fa3c6887fff57a7f4cf",
          "8d25cd97229dbf70356bda4eb3cc734031e24cf00fafcfd32dc76eb5841c7ea8",
          "34d8a73ee208d9bcdb0d956520934b4e40e69482596e8b6f73c8426b010a6f48",
          "349dfa4058c5e263123b398ae795573c4e1313c83fe68f93556cd5e8031b3c7d");

  @Test
  void loadsOnlyTheBundledRootsWithTheExpectedFingerprints() throws Exception {
    KeyStore store = SecureHttpClient.loadTrustStore();
    Set<String> fingerprints = new TreeSet<>();
    for (String resource : SecureHttpClient.ROOT_RESOURCES) {
      X509Certificate certificate = (X509Certificate) store.getCertificate(resource);
      byte[] digest = MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded());
      fingerprints.add(HexFormat.of().formatHex(digest));
      assertEquals(
          certificate.getSubjectX500Principal(),
          certificate.getIssuerX500Principal(),
          resource + " debe ser una raiz autofirmada");
    }
    assertEquals(new TreeSet<>(EXPECTED_SHA256), fingerprints);
    assertEquals(SecureHttpClient.ROOT_RESOURCES.size(), store.size());
  }

  @Test
  void contextUsesTls13() {
    assertEquals("TLSv1.3", SecureHttpClient.sslContext().getProtocol());
  }

  @Test
  void clientOnlyOffersTls13() {
    HttpClient client = SecureHttpClient.create(Duration.ofSeconds(5));
    assertArrayEquals(new String[] {"TLSv1.3"}, client.sslParameters().getProtocols());
  }

  @Test
  void clientIgnoresTheSystemProxy() {
    HttpClient client = SecureHttpClient.create(Duration.ofSeconds(5));
    ProxySelector selector = client.proxy().orElseThrow();
    assertTrue(selector.select(URI.create("https://example.com")).contains(Proxy.NO_PROXY));
  }
}
