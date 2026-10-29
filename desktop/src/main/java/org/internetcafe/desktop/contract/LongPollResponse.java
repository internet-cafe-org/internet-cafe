package org.internetcafe.desktop.contract;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public record LongPollResponse(
    @JsonProperty("evento_id") String eventoId, String tipo, Map<String, Object> datos) {}
