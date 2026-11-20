package org.internetcafe.desktop.identity;

import com.sun.jna.platform.win32.Crypt32Util;
import com.sun.jna.platform.win32.Win32Exception;
import java.security.GeneralSecurityException;

public final class WindowsDpapiProtector implements SecretProtector {
  public WindowsDpapiProtector() {
    if (!System.getProperty("os.name", "").startsWith("Windows")) {
      throw new IllegalStateException("Windows DPAPI is available only on Windows");
    }
  }

  @Override
  public byte[] protect(byte[] plaintext) throws GeneralSecurityException {
    try {
      return Crypt32Util.cryptProtectData(plaintext);
    } catch (Win32Exception exception) {
      throw new GeneralSecurityException("Unable to protect data with Windows DPAPI", exception);
    }
  }

  @Override
  public byte[] unprotect(byte[] ciphertext) throws GeneralSecurityException {
    try {
      return Crypt32Util.cryptUnprotectData(ciphertext);
    } catch (Win32Exception exception) {
      throw new GeneralSecurityException("Unable to unprotect data with Windows DPAPI", exception);
    }
  }
}
