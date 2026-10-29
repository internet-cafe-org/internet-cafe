package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class AppConfigTest {
  private String previousApiBaseUrl;

  @AfterEach
  void restoreApiBaseUrl() {
    if (previousApiBaseUrl == null) {
      System.clearProperty("api.base.url");
    } else {
      System.setProperty("api.base.url", previousApiBaseUrl);
    }
  }

  @Test
  void systemPropertyOverrideIsNormalized() {
    previousApiBaseUrl = System.getProperty("api.base.url");
    System.setProperty("api.base.url", "https://api.example.invalid/");

    assertEquals("https://api.example.invalid", AppConfig.getApiBaseUrl());
  }

  @Test
  void rejectsNonHttpBaseUrls() {
    previousApiBaseUrl = System.getProperty("api.base.url");
    System.setProperty("api.base.url", "file:///tmp/api");

    assertThrows(IllegalArgumentException.class, AppConfig::getApiBaseUrl);
  }

  @Test
  void rejectsCredentialsInBaseUrl() {
    previousApiBaseUrl = System.getProperty("api.base.url");
    System.setProperty("api.base.url", "https://user:password@example.invalid");

    assertThrows(IllegalArgumentException.class, AppConfig::getApiBaseUrl);
  }
}
