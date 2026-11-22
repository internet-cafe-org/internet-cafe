package org.internetcafe.desktop.identity;

import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.GeneralSecurityException;

public final class ProtectedFile {
  private final Path path;
  private final SecretProtector protector;

  public ProtectedFile(Path path, SecretProtector protector) {
    if (path == null || protector == null) {
      throw new IllegalArgumentException("Path and secret protector are required");
    }
    this.path = path.toAbsolutePath().normalize();
    this.protector = protector;
  }

  public byte[] read() throws IOException, GeneralSecurityException {
    byte[] ciphertext = Files.readAllBytes(path);
    try {
      return protector.unprotect(ciphertext);
    } finally {
      java.util.Arrays.fill(ciphertext, (byte) 0);
    }
  }

  public void write(byte[] plaintext) throws IOException, GeneralSecurityException {
    byte[] ciphertext = protector.protect(plaintext);
    try {
      writeAtomically(ciphertext, true);
    } finally {
      java.util.Arrays.fill(ciphertext, (byte) 0);
    }
  }

  public boolean writeIfAbsent(byte[] plaintext) throws IOException, GeneralSecurityException {
    byte[] ciphertext = protector.protect(plaintext);
    try {
      writeAtomically(ciphertext, false);
      return true;
    } catch (java.nio.file.FileAlreadyExistsException exception) {
      return false;
    } finally {
      java.util.Arrays.fill(ciphertext, (byte) 0);
    }
  }

  private void writeAtomically(byte[] ciphertext, boolean replace) throws IOException {
    Files.createDirectories(path.getParent());
    Path temporaryFile = Files.createTempFile(path.getParent(), "protected-", ".tmp");
    try {
      Files.write(temporaryFile, ciphertext);
      try {
        move(temporaryFile, replace, replace);
      } catch (AtomicMoveNotSupportedException exception) {
        move(temporaryFile, replace, false);
      }
    } finally {
      Files.deleteIfExists(temporaryFile);
    }
  }

  private void move(Path temporaryFile, boolean replace, boolean atomic) throws IOException {
    if (atomic && replace) {
      Files.move(
          temporaryFile, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    } else if (atomic) {
      Files.move(temporaryFile, path, StandardCopyOption.ATOMIC_MOVE);
    } else if (replace) {
      Files.move(temporaryFile, path, StandardCopyOption.REPLACE_EXISTING);
    } else {
      Files.move(temporaryFile, path);
    }
  }
}
