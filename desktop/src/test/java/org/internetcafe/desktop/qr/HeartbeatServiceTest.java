package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.internetcafe.desktop.contract.HeartbeatResponse;
import org.internetcafe.desktop.services.ApiClient;
import org.junit.jupiter.api.Test;

class HeartbeatServiceTest {

  private final List<String> sent = new ArrayList<>();
  private final List<String> closedSessions = new ArrayList<>();
  private final List<String> closedReasons = new ArrayList<>();

  private static HeartbeatResponse response(String status, String reason) {
    return new HeartbeatResponse("2026-11-17T10:00:00Z", "kiosk", status, "s1", reason);
  }

  private HeartbeatService service(HeartbeatService.Sender sender) {
    return new HeartbeatService(
        sender,
        (sessionId, reason) -> {
          closedSessions.add(sessionId);
          closedReasons.add(reason);
        });
  }

  @Test
  void heartbeatIsSentEvenWithoutSession() {
    HeartbeatService service =
        service(
            id -> {
              sent.add(id);
              return response("none", null);
            });
    service.beat();
    assertEquals(1, sent.size());
    assertNull(sent.get(0));
  }

  @Test
  void sendsTheCurrentSessionId() {
    HeartbeatService service =
        service(
            id -> {
              sent.add(id);
              return response("active", null);
            });
    service.setSessionId("s1");
    service.beat();
    assertEquals("s1", sent.get(0));
    assertTrue(closedSessions.isEmpty());
  }

  @Test
  void remoteCloseNotifiesOnceWithTheReasonAndClearsTheSession() {
    HeartbeatService service =
        service(
            id -> {
              sent.add(id);
              return response("ended", "admin_forced");
            });
    service.setSessionId("s1");
    service.beat();
    service.beat();
    assertEquals(List.of("s1"), closedSessions);
    assertEquals(List.of("admin_forced"), closedReasons);
    assertEquals("s1", sent.get(0));
    assertNull(sent.get(1));
  }

  @Test
  void endedWithoutAKnownSessionIsIgnored() {
    HeartbeatService service = service(id -> response("ended", "user_logout_web"));
    service.beat();
    assertTrue(closedSessions.isEmpty());
  }

  @Test
  void failedHeartbeatDoesNotThrowAndKeepsTheSession() {
    boolean[] fail = {true};
    HeartbeatService service =
        service(
            id -> {
              if (fail[0]) {
                throw new IOException("sin red");
              }
              sent.add(id);
              return response("active", null);
            });
    service.setSessionId("s1");
    assertDoesNotThrow(service::beat);
    fail[0] = false;
    service.beat();
    assertEquals("s1", sent.get(0));
    assertTrue(closedSessions.isEmpty());
  }

  @Test
  void remoteCloseIsDetectedWithin65Seconds() {
    long worstCase = HeartbeatService.INTERVAL_SECONDS + ApiClient.HEARTBEAT_TIMEOUT.toSeconds();
    assertTrue(worstCase <= 65, "peor caso: " + worstCase + " s");
  }
}
