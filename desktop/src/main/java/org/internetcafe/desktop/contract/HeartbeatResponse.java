package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** Response of {@code POST /api/v1/machine/heartbeat} (contract section 6). */
@JsonIgnoreProperties(ignoreUnknown = true)
public record HeartbeatResponse(
    @JsonProperty("server_time") String serverTime,
    @JsonProperty("mode") String mode,
    @JsonProperty("session_status") String sessionStatus,
    @JsonProperty("session_id") String sessionId,
    @JsonProperty("end_reason") String endReason) {

  public static final String ENDED = "ended";

  /** True when the session the machine reported was already closed (remote close). */
  public boolean ended() {
    return ENDED.equals(sessionStatus);
  }
}
