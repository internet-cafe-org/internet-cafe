package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Una sesión de acceso cerrada del equipo (RF-EQU-09: últimos 5 accesos).
 *
 * <p>Mapeada desde {@code GET /api/v1/machine/sessions/recent}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record RecentSession(
    @JsonProperty("started_at") String startedAt,
    @JsonProperty("ended_at") String endedAt,
    @JsonProperty("end_reason") String endReason) {}
