package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public record EnrollmentRequest(
    Map<String, Object> jwk, @JsonProperty("prueba_posesion") String pruebaPosesion) {}
