package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Enrollment data of this machine. Unknown fields are ignored so that enrollment files written
 * before SEC-14, which still hold the retired provisional credential, can be loaded.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record EnrollmentResponse(
    @JsonProperty("machine_id") String machineId,
    String code,
    String lab,
    String mode,
    String keyid) {}
