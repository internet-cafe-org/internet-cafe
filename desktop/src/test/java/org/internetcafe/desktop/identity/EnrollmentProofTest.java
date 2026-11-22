package org.internetcafe.desktop.identity;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.util.Base64;
import org.junit.jupiter.api.Test;

class EnrollmentProofTest {
  @Test
  void preservesFixedWidthWhenDerIntegerHasASignPaddingByte() throws Exception {
    byte[] derSignature = {0x30, 0x07, 0x02, 0x01, 0x01, 0x02, 0x02, 0x00, (byte) 0x80};

    byte[] rawSignature = EnrollmentProof.derToRaw(derSignature);
    byte[] expected = new byte[64];
    expected[31] = 1;
    expected[63] = (byte) 0x80;

    assertEquals(64, rawSignature.length);
    assertArrayEquals(expected, rawSignature);
  }

  @Test
  void signsExactUtf8CodeAsBase64UrlP1363Proof() throws Exception {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"));
    var keyPair = generator.generateKeyPair();
    String code = "código-de-prueba-123";

    String proof = EnrollmentProof.sign(code, keyPair.getPrivate());
    byte[] rawSignature = Base64.getUrlDecoder().decode(proof);
    Signature verifier = Signature.getInstance("SHA256withECDSAinP1363Format");
    verifier.initVerify(keyPair.getPublic());
    verifier.update(code.getBytes(StandardCharsets.UTF_8));

    assertEquals(64, rawSignature.length);
    assertEquals(-1, proof.indexOf('='));
    assertTrue(verifier.verify(rawSignature));
  }
}
