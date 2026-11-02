package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Response of {@code POST /api/v1/machine/challenges}. */
public record ChallengeResponse(
    @JsonProperty("challenge_id") String challengeId,
    @JsonProperty("qr_url") String qrUrl,
    @JsonProperty("expires_at") String expiresAt,
    @JsonProperty("rotate_after_s") int rotateAfterSeconds) {}
