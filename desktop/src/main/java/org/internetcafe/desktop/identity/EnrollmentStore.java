package org.internetcafe.desktop.identity;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import org.internetcafe.desktop.contract.EnrollmentResponse;

public final class EnrollmentStore {
  private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

  private final ProtectedFile protectedFile;

  public EnrollmentStore(ProtectedFile protectedFile) {
    if (protectedFile == null) {
      throw new IllegalArgumentException("Protected file is required");
    }
    this.protectedFile = protectedFile;
  }

  public static EnrollmentStore underLocalAppData(SecretProtector protector) throws IOException {
    String localAppData = System.getenv("LOCALAPPDATA");
    if (localAppData == null || localAppData.isBlank()) {
      throw new IOException("The LOCALAPPDATA environment variable is not available");
    }
    Path enrollmentPath = Path.of(localAppData, "InternetCafe", "enrollment.bin");
    return new EnrollmentStore(new ProtectedFile(enrollmentPath, protector));
  }

  public void save(EnrollmentResponse response) throws IOException, GeneralSecurityException {
    byte[] serialized = OBJECT_MAPPER.writeValueAsBytes(response);
    try {
      protectedFile.write(serialized);
    } finally {
      Arrays.fill(serialized, (byte) 0);
    }
  }

  public EnrollmentResponse load() throws IOException, GeneralSecurityException {
    byte[] serialized = protectedFile.read();
    try {
      return OBJECT_MAPPER.readValue(serialized, EnrollmentResponse.class);
    } catch (JsonProcessingException exception) {
      throw new IOException("Stored enrollment data is invalid", exception);
    } finally {
      Arrays.fill(serialized, (byte) 0);
    }
  }
}
