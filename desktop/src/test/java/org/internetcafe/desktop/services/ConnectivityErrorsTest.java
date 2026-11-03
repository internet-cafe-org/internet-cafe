package org.internetcafe.desktop.services;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import org.junit.jupiter.api.Test;

class ConnectivityErrorsTest {

  @Test
  void networkFailuresCountAsConnectionFailures() {
    assertTrue(ConnectivityErrors.isConnectionFailure(new IOException("no route")));
  }

  @Test
  void gatewayAndUnavailableAnswersCountAsConnectionFailures() {
    assertTrue(ConnectivityErrors.isConnectionFailure(new ApiException(502)));
    assertTrue(ConnectivityErrors.isConnectionFailure(new ApiException(503)));
    assertTrue(ConnectivityErrors.isConnectionFailure(new ApiException(504)));
  }

  @Test
  void otherHttpErrorsDoNotCount() {
    assertFalse(ConnectivityErrors.isConnectionFailure(new ApiException(401)));
    assertFalse(ConnectivityErrors.isConnectionFailure(new ApiException(404)));
    assertFalse(ConnectivityErrors.isConnectionFailure(new ApiException(500)));
  }

  @Test
  void unreadableResponsesDoNotCount() {
    JsonProcessingException bad =
        assertThrows(
            JsonProcessingException.class, () -> new ObjectMapper().readValue("{", Object.class));
    assertFalse(ConnectivityErrors.isConnectionFailure(bad));
  }
}
