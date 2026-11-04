package org.internetcafe.desktop.services;

import java.io.IOException;
import java.io.InputStream;
import java.net.ProxySelector;
import java.net.http.HttpClient;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.time.Duration;
import java.util.List;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.TrustManagerFactory;

/**
 * Crea el HttpClient del escritorio (DSK-13): confia solo en las raices empaquetadas en la app
 * (Let's Encrypt y Google Trust Services, las autoridades que usa Render), ignora el proxy del
 * sistema y negocia unicamente TLS 1.3.
 */
public final class SecureHttpClient {

  static final String TLS_VERSION = "TLSv1.3";
  static final List<String> ROOT_RESOURCES =
      List.of(
          "isrg-root-x1.pem",
          "isrg-root-x2.pem",
          "gts-root-r1.pem",
          "gts-root-r2.pem",
          "gts-root-r3.pem",
          "gts-root-r4.pem");

  private SecureHttpClient() {}

  public static HttpClient create(Duration connectTimeout) {
    SSLParameters parameters = new SSLParameters();
    parameters.setProtocols(new String[] {TLS_VERSION});
    return HttpClient.newBuilder()
        .connectTimeout(connectTimeout)
        .proxy(ProxySelector.of(null))
        .sslContext(sslContext())
        .sslParameters(parameters)
        .build();
  }

  static SSLContext sslContext() {
    try {
      TrustManagerFactory factory =
          TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
      factory.init(loadTrustStore());
      SSLContext context = SSLContext.getInstance(TLS_VERSION);
      context.init(null, factory.getTrustManagers(), null);
      return context;
    } catch (GeneralSecurityException | IOException e) {
      throw new IllegalStateException("No se pudo crear el contexto TLS", e);
    }
  }

  static KeyStore loadTrustStore() throws GeneralSecurityException, IOException {
    KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
    store.load(null, null);
    CertificateFactory certificates = CertificateFactory.getInstance("X.509");
    for (String resource : ROOT_RESOURCES) {
      try (InputStream in = SecureHttpClient.class.getResourceAsStream("/truststore/" + resource)) {
        if (in == null) {
          throw new IOException("Falta la raiz de confianza " + resource);
        }
        store.setCertificateEntry(resource, certificates.generateCertificate(in));
      }
    }
    return store;
  }
}
