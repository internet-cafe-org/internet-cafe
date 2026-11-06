package org.internetcafe.desktop;

import java.net.URI;

public final class AppConfig {
  private static final String DEFAULT_API_BASE_URL = "http://localhost:8000";

  private AppConfig() {}

  public static String getApiBaseUrl() {
    String baseUrl = System.getProperty("api.base.url");
    if (baseUrl == null || baseUrl.isBlank()) {
      baseUrl = System.getenv("API_BASE_URL");
    }
    if (baseUrl == null || baseUrl.isBlank()) {
      baseUrl = DEFAULT_API_BASE_URL;
    }

    URI uri = URI.create(baseUrl.trim());
    String scheme = uri.getScheme();
    if (uri.getHost() == null
        || !("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))
        || uri.getRawUserInfo() != null
        || uri.getRawQuery() != null
        || uri.getRawFragment() != null) {
      throw new IllegalArgumentException(
          "API_BASE_URL must be an HTTP(S) URL without credentials, a query, or a fragment");
    }

    String normalizedUrl = uri.toString();
    while (normalizedUrl.endsWith("/")) {
      normalizedUrl = normalizedUrl.substring(0, normalizedUrl.length() - 1);
    }
    return normalizedUrl;
  }
}
