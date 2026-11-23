package org.internetcafe.desktop.identity;

import java.io.IOException;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Base64;

public final class MachineIdentityPasswordStore {
  private final ProtectedFile protectedFile;

  public MachineIdentityPasswordStore(ProtectedFile protectedFile) {
    if (protectedFile == null) {
      throw new IllegalArgumentException("Protected file is required");
    }
    this.protectedFile = protectedFile;
  }

  public static MachineIdentityPasswordStore underLocalAppData(SecretProtector protector)
      throws IOException {
    String localAppData = System.getenv("LOCALAPPDATA");
    if (localAppData == null || localAppData.isBlank()) {
      throw new IOException("The LOCALAPPDATA environment variable is not available");
    }
    Path passwordPath = Path.of(localAppData, "InternetCafe", "machine-identity-password.bin");
    return new MachineIdentityPasswordStore(new ProtectedFile(passwordPath, protector));
  }

  public char[] loadOrCreate() throws IOException, GeneralSecurityException {
    try {
      return decodePassword(protectedFile.read());
    } catch (java.nio.file.NoSuchFileException exception) {
      byte[] secret = new byte[32];
      new SecureRandom().nextBytes(secret);
      byte[] encoded = Base64.getUrlEncoder().withoutPadding().encode(secret);
      try {
        if (protectedFile.writeIfAbsent(encoded)) {
          return toPassword(encoded);
        }
        return decodePassword(protectedFile.read());
      } finally {
        java.util.Arrays.fill(secret, (byte) 0);
        java.util.Arrays.fill(encoded, (byte) 0);
      }
    }
  }

  public char[] loadExisting() throws IOException, GeneralSecurityException {
    return decodePassword(protectedFile.read());
  }

  private static char[] decodePassword(byte[] encoded) throws GeneralSecurityException {
    byte[] decoded = null;
    try {
      decoded = Base64.getUrlDecoder().decode(encoded);
      if (decoded.length != 32) {
        throw new GeneralSecurityException("Stored machine identity password is invalid");
      }
      return toPassword(encoded);
    } catch (IllegalArgumentException exception) {
      throw new GeneralSecurityException("Stored machine identity password is invalid", exception);
    } finally {
      if (decoded != null) {
        java.util.Arrays.fill(decoded, (byte) 0);
      }
      java.util.Arrays.fill(encoded, (byte) 0);
    }
  }

  private static char[] toPassword(byte[] encoded) {
    char[] password = new char[encoded.length];
    for (int index = 0; index < encoded.length; index++) {
      password[index] = (char) Byte.toUnsignedInt(encoded[index]);
    }
    return password;
  }
}
