package org.internetcafe.desktop.identity;

import java.nio.charset.StandardCharsets;
import java.security.AlgorithmParameters;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECFieldFp;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.ECParameterSpec;
import java.util.Base64;

public record PublicJwk(String kty, String crv, String x, String y) {
  private static final String P256 = "P-256";

  public PublicJwk {
    if (!"EC".equals(kty) || !P256.equals(crv)) {
      throw new IllegalArgumentException("Only public P-256 EC JWKs are supported");
    }
    if (!isCoordinate(x) || !isCoordinate(y)) {
      throw new IllegalArgumentException("P-256 JWK coordinates must be 32-byte base64url values");
    }
  }

  public static PublicJwk from(ECPublicKey publicKey) {
    if (publicKey == null || !isP256(publicKey.getParams())) {
      throw new IllegalArgumentException("Public key must use the P-256 curve");
    }
    return new PublicJwk(
        "EC",
        P256,
        encodeCoordinate(publicKey.getW().getAffineX().toByteArray()),
        encodeCoordinate(publicKey.getW().getAffineY().toByteArray()));
  }

  public String toJson() {
    return "{\"crv\":\"P-256\",\"kty\":\"EC\",\"x\":\"" + x + "\",\"y\":\"" + y + "\"}";
  }

  public String thumbprint() {
    try {
      byte[] digest =
          MessageDigest.getInstance("SHA-256").digest(toJson().getBytes(StandardCharsets.UTF_8));
      return Base64.getUrlEncoder().withoutPadding().encodeToString(digest);
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException("SHA-256 is required by the Java runtime", exception);
    }
  }

  public boolean matchesThumbprint(String expected) {
    if (expected == null) {
      return false;
    }
    byte[] expectedBytes;
    try {
      expectedBytes = Base64.getUrlDecoder().decode(expected);
    } catch (IllegalArgumentException exception) {
      return false;
    }
    byte[] actualBytes = Base64.getUrlDecoder().decode(thumbprint());
    return MessageDigest.isEqual(actualBytes, expectedBytes);
  }

  private static boolean isCoordinate(String value) {
    if (value == null) {
      return false;
    }
    try {
      byte[] decoded = Base64.getUrlDecoder().decode(value);
      return decoded.length == 32
          && Base64.getUrlEncoder().withoutPadding().encodeToString(decoded).equals(value);
    } catch (IllegalArgumentException exception) {
      return false;
    }
  }

  static boolean isP256(ECParameterSpec actual) {
    try {
      AlgorithmParameters parameters = AlgorithmParameters.getInstance("EC");
      parameters.init(new ECGenParameterSpec("secp256r1"));
      ECParameterSpec expected = parameters.getParameterSpec(ECParameterSpec.class);
      return actual.getCurve().getField() instanceof ECFieldFp actualField
          && expected.getCurve().getField() instanceof ECFieldFp expectedField
          && actualField.getP().equals(expectedField.getP())
          && actual.getCurve().getA().equals(expected.getCurve().getA())
          && actual.getCurve().getB().equals(expected.getCurve().getB())
          && actual.getGenerator().equals(expected.getGenerator())
          && actual.getOrder().equals(expected.getOrder())
          && actual.getCofactor() == expected.getCofactor();
    } catch (NoSuchAlgorithmException
        | java.security.spec.InvalidParameterSpecException exception) {
      throw new IllegalStateException("P-256 is required by the Java runtime", exception);
    }
  }

  private static String encodeCoordinate(byte[] coordinate) {
    int firstNonZero = 0;
    while (firstNonZero < coordinate.length - 1 && coordinate[firstNonZero] == 0) {
      firstNonZero++;
    }
    int coordinateLength = coordinate.length - firstNonZero;
    if (coordinateLength > 32) {
      throw new IllegalArgumentException("P-256 coordinate exceeds 32 bytes");
    }
    byte[] fixedWidth = new byte[32];
    System.arraycopy(coordinate, firstNonZero, fixedWidth, 32 - coordinateLength, coordinateLength);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(fixedWidth);
  }
}
