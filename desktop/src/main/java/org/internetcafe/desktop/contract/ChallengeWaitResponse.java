package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** Response of {@code GET /api/v1/machine/challenges/wait}: status is "approved" or "waiting". */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ChallengeWaitResponse(
    @JsonProperty("status") String status,
    @JsonProperty("session") Session session,
    @JsonProperty("user") User user) {

  public static final String APPROVED = "approved";
  private static final String DEFAULT_NAME = "Usuario";
  private static final String DEFAULT_CODE = "****";

  /** Session data returned when the challenge was approved. */
  @JsonIgnoreProperties(ignoreUnknown = true)
  public record Session(
      @JsonProperty("id") String id,
      @JsonProperty("status") String status,
      @JsonProperty("started_at") String startedAt) {}

  /** Student data returned when the challenge was approved (the code is already masked). */
  @JsonIgnoreProperties(ignoreUnknown = true)
  public record User(
      @JsonProperty("full_name") String fullName,
      @JsonProperty("student_code_masked") String studentCodeMasked) {}

  public boolean approved() {
    return APPROVED.equals(status);
  }

  public String displayName() {
    if (user == null || user.fullName() == null || user.fullName().isBlank()) {
      return DEFAULT_NAME;
    }
    return user.fullName();
  }

  public String maskedStudentCode() {
    if (user == null || user.studentCodeMasked() == null || user.studentCodeMasked().isBlank()) {
      return DEFAULT_CODE;
    }
    return user.studentCodeMasked();
  }
}
