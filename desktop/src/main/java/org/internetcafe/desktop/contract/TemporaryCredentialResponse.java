package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;

public record TemporaryCredentialResponse(
    @JsonProperty("credencial_temporal") String credencialTemporal,
    @JsonProperty("expiracion_segundos") Integer expiracionSegundos) {}
