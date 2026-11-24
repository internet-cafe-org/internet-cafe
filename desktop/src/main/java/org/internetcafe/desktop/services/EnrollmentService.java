package org.internetcafe.desktop.services;

import java.io.IOException;
import java.security.GeneralSecurityException;
import org.internetcafe.desktop.contract.EnrollmentRequest;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.identity.EnrollmentProof;
import org.internetcafe.desktop.identity.EnrollmentStore;
import org.internetcafe.desktop.identity.MachineIdentity;
import org.internetcafe.desktop.identity.MachineIdentityStore;

public final class EnrollmentService {
  private final ApiClient apiClient;
  private final MachineIdentityStore identityStore;
  private final EnrollmentStore enrollmentStore;

  public EnrollmentService(
      ApiClient apiClient, MachineIdentityStore identityStore, EnrollmentStore enrollmentStore) {
    if (apiClient == null || identityStore == null || enrollmentStore == null) {
      throw new IllegalArgumentException("Enrollment dependencies are required");
    }
    this.apiClient = apiClient;
    this.identityStore = identityStore;
    this.enrollmentStore = enrollmentStore;
  }

  public EnrollmentResponse enroll(String enrollmentCode)
      throws IOException, GeneralSecurityException, InterruptedException {
    if (enrollmentCode == null
        || enrollmentCode.isBlank()
        || enrollmentCode.length() < 8
        || enrollmentCode.length() > 64) {
      throw new IllegalArgumentException(
          "Enrollment code must contain between 8 and 64 characters");
    }

    MachineIdentity identity = identityStore.loadOrCreate();
    String proof = EnrollmentProof.sign(enrollmentCode, identity.privateKey());
    EnrollmentResponse response =
        apiClient.enroll(new EnrollmentRequest(enrollmentCode, identity.publicJwk(), proof));
    if (response == null
        || !identity.publicJwk().matchesThumbprint(response.keyid())
        || response.machineId() == null
        || response.code() == null
        || response.code().isBlank()
        || response.mode() == null) {
      throw new EnrollmentCommitException(
          new GeneralSecurityException("Enrollment response does not match the local identity"));
    }
    try {
      enrollmentStore.save(response);
    } catch (IOException | GeneralSecurityException exception) {
      throw new EnrollmentCommitException(exception);
    }
    return response;
  }
}
