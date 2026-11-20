package org.internetcafe.desktop;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

public final class WindowsElevation {
  private static final String CHECK_ADMINISTRATOR =
      "$principal = New-Object Security.Principal.WindowsPrincipal("
          + "[Security.Principal.WindowsIdentity]::GetCurrent()); "
          + "if ($principal.IsInRole("
          + "[Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 0 } else { exit 1 }";

  private WindowsElevation() {}

  public static boolean isAdministrator() throws IOException, InterruptedException {
    if (!System.getProperty("os.name", "").startsWith("Windows")) {
      return false;
    }

    Process process =
        new ProcessBuilder(
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                CHECK_ADMINISTRATOR)
            .redirectError(ProcessBuilder.Redirect.DISCARD)
            .redirectOutput(ProcessBuilder.Redirect.DISCARD)
            .start();
    if (!process.waitFor(10, TimeUnit.SECONDS)) {
      process.destroyForcibly();
      throw new IOException("Timed out while checking Windows administrator privileges");
    }
    if (process.exitValue() == 0) {
      return true;
    }
    if (process.exitValue() == 1) {
      return false;
    }
    throw new IOException("Unable to check Windows administrator privileges");
  }
}
