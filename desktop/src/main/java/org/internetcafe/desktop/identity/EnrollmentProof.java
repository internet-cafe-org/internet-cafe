package org.internetcafe.desktop.identity;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.PrivateKey;
import java.security.Signature;
import java.util.Base64;

public final class EnrollmentProof {
  private static final int COORDINATE_LENGTH = 32;

  private EnrollmentProof() {}

  public static String sign(String enrollmentCode, PrivateKey privateKey)
      throws GeneralSecurityException {
    if (enrollmentCode == null || privateKey == null) {
      throw new IllegalArgumentException("Enrollment code and private key are required");
    }
    Signature signer = Signature.getInstance("SHA256withECDSA");
    signer.initSign(privateKey);
    signer.update(enrollmentCode.getBytes(StandardCharsets.UTF_8));
    return Base64.getUrlEncoder().withoutPadding().encodeToString(derToRaw(signer.sign()));
  }

  static byte[] derToRaw(byte[] derSignature) throws GeneralSecurityException {
    if (derSignature == null || derSignature.length < 8 || derSignature[0] != 0x30) {
      throw new GeneralSecurityException("ECDSA signature has an invalid DER sequence");
    }
    int sequenceLength = derSignature[1] & 0xff;
    if (sequenceLength != derSignature.length - 2 || sequenceLength >= 128) {
      throw new GeneralSecurityException("ECDSA signature has an invalid DER length");
    }
    int position = 2;
    byte[] r = readInteger(derSignature, position);
    position += 2 + (derSignature[position + 1] & 0xff);
    byte[] s = readInteger(derSignature, position);
    position += 2 + (derSignature[position + 1] & 0xff);
    if (position != derSignature.length) {
      throw new GeneralSecurityException("ECDSA signature contains trailing data");
    }

    byte[] rawSignature = new byte[COORDINATE_LENGTH * 2];
    copyCoordinate(r, rawSignature, 0);
    copyCoordinate(s, rawSignature, COORDINATE_LENGTH);
    return rawSignature;
  }

  private static byte[] readInteger(byte[] der, int position) throws GeneralSecurityException {
    if (position + 2 > der.length || der[position] != 0x02) {
      throw new GeneralSecurityException("ECDSA signature has an invalid DER integer");
    }
    int length = der[position + 1] & 0xff;
    int start = position + 2;
    if (length == 0 || start + length > der.length) {
      throw new GeneralSecurityException("ECDSA signature has an invalid integer length");
    }
    int firstNonZero = der[start] == 0 ? start + 1 : start;
    if (firstNonZero == start + length || (der[start] & 0x80) != 0) {
      throw new GeneralSecurityException("ECDSA signature integer is not positive");
    }
    byte[] value = new byte[start + length - firstNonZero];
    System.arraycopy(der, firstNonZero, value, 0, value.length);
    if (value.length > COORDINATE_LENGTH) {
      throw new GeneralSecurityException("ECDSA signature coordinate exceeds P-256");
    }
    return value;
  }

  private static void copyCoordinate(byte[] coordinate, byte[] rawSignature, int offset) {
    System.arraycopy(
        coordinate,
        0,
        rawSignature,
        offset + COORDINATE_LENGTH - coordinate.length,
        coordinate.length);
  }
}
