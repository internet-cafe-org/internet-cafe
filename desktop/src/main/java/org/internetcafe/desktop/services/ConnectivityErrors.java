package org.internetcafe.desktop.services;

import com.fasterxml.jackson.core.JsonProcessingException;
import java.io.IOException;

/** Tells apart "the network or the API is down" from errors that retrying would not fix. */
public final class ConnectivityErrors {

  private ConnectivityErrors() {}

  /**
   * True for I/O failures (no network, timeouts) and for 502, 503 and 504 answers (the API is
   * waking up). False for other HTTP errors and for unreadable response bodies.
   */
  public static boolean isConnectionFailure(Throwable error) {
    if (error instanceof ApiException apiError) {
      int status = apiError.getStatusCode();
      return status == 502 || status == 503 || status == 504;
    }
    return error instanceof IOException && !(error instanceof JsonProcessingException);
  }
}
