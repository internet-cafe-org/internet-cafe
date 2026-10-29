package org.internetcafe.desktop.services;

import java.io.IOException;

public final class ApiException extends IOException {
  private final int statusCode;

  public ApiException(int statusCode) {
    super("API request failed with HTTP status " + statusCode);
    this.statusCode = statusCode;
  }

  public int getStatusCode() {
    return statusCode;
  }
}
