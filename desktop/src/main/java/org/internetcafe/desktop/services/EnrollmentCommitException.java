package org.internetcafe.desktop.services;

import java.io.IOException;

public final class EnrollmentCommitException extends IOException {
  public EnrollmentCommitException(Throwable cause) {
    super("The server accepted the enrollment but the result could not be saved safely", cause);
  }
}
