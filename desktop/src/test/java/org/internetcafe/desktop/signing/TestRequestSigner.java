package org.internetcafe.desktop.signing;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECGenParameterSpec;
import org.internetcafe.desktop.identity.PublicJwk;

public final class TestRequestSigner {
  private TestRequestSigner() {}

  public static RequestSigner create() {
    try {
      KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
      generator.initialize(new ECGenParameterSpec("secp256r1"));
      KeyPair keyPair = generator.generateKeyPair();
      return new RequestSigner(
          keyPair.getPrivate(), PublicJwk.from((ECPublicKey) keyPair.getPublic()));
    } catch (java.security.GeneralSecurityException exception) {
      throw new IllegalStateException("Unable to create test signing key", exception);
    }
  }
}
