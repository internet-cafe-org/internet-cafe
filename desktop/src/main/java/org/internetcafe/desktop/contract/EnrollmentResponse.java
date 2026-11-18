package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;

public record EnrollmentResponse(
    @JsonProperty("machine_id") String machineId,
    String code,
    String lab,
    String mode,
    String keyid,
    @JsonProperty("provisional_credential") String provisionalCredential) {}
