package org.internetcafe.desktop.contract;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class HeartbeatResponseTest {

  private static final ObjectMapper MAPPER = new ObjectMapper();

  @Test
  void parsesAnEndedHeartbeatAndIgnoresUnknownFields() throws Exception {
    String json =
        "{\"server_time\":\"2026-11-17T10:00:00Z\",\"mode\":\"kiosk\","
            + "\"session_status\":\"ended\",\"session_id\":\"abc\","
            + "\"end_reason\":\"admin_forced\",\"extra\":1}";
    HeartbeatResponse response = MAPPER.readValue(json, HeartbeatResponse.class);
    assertTrue(response.ended());
    assertEquals("admin_forced", response.endReason());
    assertEquals("abc", response.sessionId());
  }

  @Test
  void noneIsNotEnded() throws Exception {
    String json =
        "{\"server_time\":\"2026-11-17T10:00:00Z\",\"mode\":\"kiosk\",\"session_status\":\"none\"}";
    assertFalse(MAPPER.readValue(json, HeartbeatResponse.class).ended());
  }
}
