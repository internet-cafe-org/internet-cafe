package org.internetcafe.desktop.signing;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.PrivateKey;
import java.security.Signature;
import java.util.Base64;
import java.util.Locale;
import org.internetcafe.desktop.identity.PublicJwk;

/**
 * Signs HTTP requests following RFC 9421 (ecdsa-p256-sha256) with a Content-Digest (RFC 9530). The
 * output must match contracts/test-vectors/vectores.json byte by byte.
 */
public final class RequestSigner {
  public static final String LABEL = "sig1";
  public static final String ALGORITHM = "ecdsa-p256-sha256";
  private static final int COORDINATE_LENGTH = 32;

  private final PrivateKey privateKey;
  private final String keyId;

  public RequestSigner(PrivateKey privateKey, PublicJwk publicJwk) {
    if (privateKey == null || publicJwk == null) {
      throw new IllegalArgumentException("The private key and the public JWK are required");
    }
    this.privateKey = privateKey;
    this.keyId = publicJwk.thumbprint();
  }

  public String keyId() {
    return keyId;
  }

  /**
   * Signs one request.
   *
   * @param method HTTP method, for example POST
   * @param targetUri absolute URI built from the public API base URL plus the path
   * @param body request body, or null when there is none (no Content-Digest is added then)
   * @param created signature creation time in Unix seconds
   * @param nonce unique value for this signature
   */
  public SignedRequest sign(
      String method, String targetUri, byte[] body, long created, String nonce)
      throws GeneralSecurityException {
    if (method == null
        || method.isBlank()
        || targetUri == null
        || targetUri.isBlank()
        || nonce == null
        || nonce.isBlank()) {
      throw new IllegalArgumentException("Method, target URI and nonce are required");
    }
    boolean hasBody = body != null && body.length > 0;
    String digest = hasBody ? contentDigest(body) : null;
    String components =
        hasBody ? "\"@method\" \"@target-uri\" \"content-digest\"" : "\"@method\" \"@target-uri\"";
    String params =
        "("
            + components
            + ");created="
            + created
            + ";keyid=\""
            + keyId
            + "\";alg=\""
            + ALGORITHM
            + "\";nonce=\""
            + nonce
            + "\"";

    StringBuilder base = new StringBuilder();
    base.append("\"@method\": ").append(method.toUpperCase(Locale.ROOT)).append('\n');
    base.append("\"@target-uri\": ").append(targetUri).append('\n');
    if (hasBody) {
      base.append("\"content-digest\": ").append(digest).append('\n');
    }
    base.append("\"@signature-params\": ").append(params);
    String signatureBase = base.toString();

    byte[] raw = derToRaw(signDer(signatureBase));
    return new SignedRequest(
        signatureBase,
        LABEL + "=" + params,
        digest,
        keyId,
        Base64.getEncoder().encodeToString(raw));
  }

  /** Content-Digest header value: sha-256 over the body bytes. */
  public static String contentDigest(byte[] body) {
    try {
      byte[] hash = MessageDigest.getInstance("SHA-256").digest(body);
      return "sha-256=:" + Base64.getEncoder().encodeToString(hash) + ":";
    } catch (NoSuchAlgorithmException exception) {
      throw new IllegalStateException("SHA-256 is required by the Java runtime", exception);
    }
  }

  /** Converts a DER ECDSA signature into the 64-byte r||s form required by RFC 9421. */
  static byte[] derToRaw(byte[] der) {
    if (der == null || der.length < 8 || der[0] != 0x30) {
      throw malformed();
    }
    int[] position = {2};
    int sequenceLength = der[1] & 0xFF;
    if (sequenceLength >= 0x80) {
      if (sequenceLength != 0x81) {
        throw malformed();
      }
      sequenceLength = der[2] & 0xFF;
      position[0] = 3;
    }
    if (sequenceLength != der.length - position[0]) {
      throw malformed();
    }
    byte[] raw = new byte[COORDINATE_LENGTH * 2];
    readInteger(der, position, raw, 0);
    readInteger(der, position, raw, COORDINATE_LENGTH);
    if (position[0] != der.length) {
      throw malformed();
    }
    return raw;
  }

  private static void readInteger(byte[] der, int[] position, byte[] raw, int offset) {
    int index = position[0];
    if (index + 2 > der.length || der[index] != 0x02) {
      throw malformed();
    }
    int length = der[index + 1] & 0xFF;
    index += 2;
    if (length == 0 || length >= 0x80 || index + length > der.length) {
      throw malformed();
    }
    if ((der[index] & 0x80) != 0) {
      throw malformed();
    }
    int start = index;
    int end = index + length;
    while (end - start > 1 && der[start] == 0) {
      start++;
    }
    int size = end - start;
    if (size > COORDINATE_LENGTH) {
      throw malformed();
    }
    System.arraycopy(der, start, raw, offset + COORDINATE_LENGTH - size, size);
    position[0] = end;
  }

  private static IllegalArgumentException malformed() {
    return new IllegalArgumentException("Malformed DER ECDSA signature");
  }

  private byte[] signDer(String signatureBase) throws GeneralSecurityException {
    Signature signer = Signature.getInstance("SHA256withECDSA");
    signer.initSign(privateKey);
    signer.update(signatureBase.getBytes(StandardCharsets.UTF_8));
    return signer.sign();
  }

  /**
   * Result of signing: everything needed to build the Content-Digest, Signature-Input and Signature
   * headers.
   */
  public record SignedRequest(
      String signatureBase,
      String signatureInput,
      String contentDigest,
      String keyId,
      String signature) {

    /** Value of the Signature header: sig1=:base64: */
    public String signatureHeader() {
      return LABEL + "=:" + signature + ":";
    }
  }
}
