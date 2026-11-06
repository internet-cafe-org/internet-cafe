package org.internetcafe.desktop.services;

import java.io.IOException;

public final class ApiException extends IOException {
  private final int statusCode;
  private final String dateHeader;

  public ApiException(int statusCode) {
    this(statusCode, null);
  }

  public ApiException(int statusCode, String dateHeader) {
    super("API request failed with HTTP status " + statusCode);
    this.statusCode = statusCode;
    this.dateHeader = dateHeader;
  }

  public int getStatusCode() {
    return statusCode;
  }

  /**
   * Returns the value of the {@code Date} response header, or {@code null} if the response did not
   * include one. Populated only for 401 responses that carry {@code MACHINE_CLOCK_SKEW}.
   */
  public String dateHeader() {
    return dateHeader;
  }
}
