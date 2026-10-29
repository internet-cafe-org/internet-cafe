package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;

public record EnrollmentResponse(
    String estado, @JsonProperty("dispositivo_id") String dispositivoId) {}
