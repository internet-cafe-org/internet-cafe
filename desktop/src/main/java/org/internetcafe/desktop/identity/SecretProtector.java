package org.internetcafe.desktop.identity;

import java.security.GeneralSecurityException;

public interface SecretProtector {
  byte[] protect(byte[] plaintext) throws GeneralSecurityException;

  byte[] unprotect(byte[] ciphertext) throws GeneralSecurityException;
}
