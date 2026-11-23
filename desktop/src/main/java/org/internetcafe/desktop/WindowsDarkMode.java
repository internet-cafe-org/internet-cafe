package org.internetcafe.desktop;

import com.sun.jna.platform.win32.Advapi32Util;
import com.sun.jna.platform.win32.WinReg;

/**
 * Detecta si Windows está configurado en modo oscuro para aplicaciones.
 *
 * <p>Lee {@code HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme}:
 * 0 = modo oscuro, 1 = modo claro (o ausente = modo claro).
 */
public final class WindowsDarkMode {

  private static final String REG_PATH =
      "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
  private static final String REG_VALUE = "AppsUseLightTheme";

  private WindowsDarkMode() {}

  /**
   * Devuelve {@code true} si Windows está en modo oscuro para aplicaciones.
   * Si no se puede leer el registro (Linux, macOS, error) devuelve {@code false}.
   */
  public static boolean isSystemDarkMode() {
    try {
      if (!Advapi32Util.registryValueExists(WinReg.HKEY_CURRENT_USER, REG_PATH, REG_VALUE)) {
        return false;
      }
      int value = Advapi32Util.registryGetIntValue(WinReg.HKEY_CURRENT_USER, REG_PATH, REG_VALUE);
      return value == 0; // 0 = dark, 1 = light
    } catch (Exception e) {
      return false;
    }
  }
}
