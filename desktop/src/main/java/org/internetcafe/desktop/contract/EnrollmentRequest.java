package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.internetcafe.desktop.identity.PublicJwk;

public record EnrollmentRequest(
    @JsonProperty("enrollment_code") String enrollmentCode, PublicJwk jwk, String proof) {}
