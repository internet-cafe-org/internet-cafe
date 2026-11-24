package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Un acceso reciente del estudiante en cualquiera de los equipos (RF-EQU-09: últimos 5 accesos).
 *
 * <p>Mapeado desde {@code recent_accesses} de {@code GET /api/v1/machine/sessions/current}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record RecentSession(
    @JsonProperty("machine_code") String machineCode,
    @JsonProperty("lab") String lab,
    @JsonProperty("started_at") String startedAt,
    @JsonProperty("ended_at") String endedAt,
    @JsonProperty("duration_s") long durationSeconds) {}