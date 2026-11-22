package org.internetcafe.desktop.signing;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.AlgorithmParameters;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECGenParameterSpec;
import java.security.spec.ECParameterSpec;
import java.security.spec.ECPoint;
import java.security.spec.ECPrivateKeySpec;
import java.security.spec.ECPublicKeySpec;
import java.util.Arrays;
import java.util.Base64;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;
import org.internetcafe.desktop.identity.PublicJwk;
import org.internetcafe.desktop.signing.RequestSigner.SignedRequest;
import org.junit.jupiter.api.DynamicTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestFactory;

class RequestSignerTest {
  private static final ObjectMapper JSON = new ObjectMapper();
  private static final ECParameterSpec P256 = p256();

  @TestFactory
  Stream<DynamicTest> matchesEveryVector() throws Exception {
    JsonNode vectors = loadVectors();
    return StreamSupport.stream(vectors.get("casos").spliterator(), false)
        .map(
            testCase ->
                DynamicTest.dynamicTest(
                    testCase.get("nombre").asText(), () -> checkCase(vectors, testCase)));
  }

  private static void checkCase(JsonNode vectors, JsonNode testCase) throws Exception {
    JsonNode keyNode = vectors.get("claves_solo_de_prueba").get(testCase.get("clave").asText());
    JsonNode publicNode = keyNode.get("jwk_publica");
    PublicJwk publicJwk =
        new PublicJwk(
            publicNode.get("kty").asText(),
            publicNode.get("crv").asText(),
            publicNode.get("x").asText(),
            publicNode.get("y").asText());
    ECPublicKey publicKey = publicKey(publicNode);

    assertEquals(keyNode.get("huella_rfc7638").asText(), publicJwk.thumbprint());
    assertEquals(publicJwk.thumbprint(), PublicJwk.from(publicKey).thumbprint());

    RequestSigner signer = new RequestSigner(privateKey(keyNode.get("jwk_privada")), publicJwk);

    JsonNode request = testCase.get("peticion");
    JsonNode bodyNode = request.get("cuerpo_utf8");
    byte[] body = bodyNode.isNull() ? null : bodyNode.asText().getBytes(StandardCharsets.UTF_8);
    String uri = request.get("base_publica").asText() + request.get("ruta").asText();
    JsonNode params = testCase.get("parametros");

    SignedRequest signed =
        signer.sign(
            request.get("metodo").asText(),
            uri,
            body,
            params.get("created").asLong(),
            params.get("nonce").asText());

    JsonNode expected = testCase.get("esperado");
    if (expected.get("content_digest").isNull()) {
      assertNull(signed.contentDigest());
    } else {
      assertEquals(expected.get("content_digest").asText(), signed.contentDigest());
    }
    assertEquals(expected.get("base_de_firma").asText(), signed.signatureBase());
    assertEquals(expected.get("signature_input").asText(), signed.signatureInput());
    assertEquals(expected.get("keyid").asText(), signed.keyId());

    byte[] raw = Base64.getDecoder().decode(signed.signature());
    assertEquals(64, raw.length);
    assertTrue(verify(publicKey, signed.signatureBase(), raw));

    byte[] reference = Base64.getDecoder().decode(testCase.get("firma_de_ejemplo").asText());
    assertTrue(verify(publicKey, signed.signatureBase(), reference));
  }

  @Test
  void derToRawRoundTripsRealSignatures() throws Exception {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"));
    KeyPair pair = generator.generateKeyPair();
    for (int i = 0; i < 25; i++) {
      Signature signer = Signature.getInstance("SHA256withECDSA");
      signer.initSign(pair.getPrivate());
      signer.update(("message-" + i).getBytes(StandardCharsets.UTF_8));
      byte[] der = signer.sign();

      byte[] raw = RequestSigner.derToRaw(der);

      assertEquals(64, raw.length);
      assertArrayEquals(der, rawToDer(raw));
    }
  }

  @Test
  void derToRawPadsShortValues() {
    byte[] der = {0x30, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x02};

    byte[] raw = RequestSigner.derToRaw(der);

    byte[] expected = new byte[64];
    expected[31] = 1;
    expected[63] = 2;
    assertArrayEquals(expected, raw);
  }

  @Test
  void derToRawDropsTheSignByte() {
    byte[] raw = new byte[64];
    raw[0] = (byte) 0x80;
    raw[32] = (byte) 0xFF;

    byte[] der = rawToDer(raw);

    assertEquals(0x00, der[4]);
    assertArrayEquals(raw, RequestSigner.derToRaw(der));
  }

  @Test
  void derToRawRejectsMalformedSignatures() {
    assertThrows(IllegalArgumentException.class, () -> RequestSigner.derToRaw(null));
    assertThrows(IllegalArgumentException.class, () -> RequestSigner.derToRaw(new byte[3]));
    assertThrows(
        IllegalArgumentException.class,
        () -> RequestSigner.derToRaw(new byte[] {0x31, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x02}));
    assertThrows(
        IllegalArgumentException.class,
        () -> RequestSigner.derToRaw(new byte[] {0x30, 0x07, 0x02, 0x01, 0x01, 0x02, 0x01, 0x02}));
  }

  @Test
  void emptyBodyIsTreatedAsNoBody() throws Exception {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"));
    KeyPair pair = generator.generateKeyPair();
    PublicJwk jwk = PublicJwk.from((ECPublicKey) pair.getPublic());
    RequestSigner signer = new RequestSigner(pair.getPrivate(), jwk);

    SignedRequest withEmpty = signer.sign("GET", "https://x.example/a", new byte[0], 1L, "bm9uY2U");
    SignedRequest withNull = signer.sign("GET", "https://x.example/a", null, 1L, "bm9uY2U");

    assertNull(withEmpty.contentDigest());
    assertEquals(withNull.signatureBase(), withEmpty.signatureBase());
  }

  @Test
  void rejectsMissingArguments() throws Exception {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"));
    KeyPair pair = generator.generateKeyPair();
    PublicJwk jwk = PublicJwk.from((ECPublicKey) pair.getPublic());
    RequestSigner signer = new RequestSigner(pair.getPrivate(), jwk);

    assertThrows(IllegalArgumentException.class, () -> new RequestSigner(null, jwk));
    assertThrows(IllegalArgumentException.class, () -> new RequestSigner(pair.getPrivate(), null));
    assertThrows(
        IllegalArgumentException.class, () -> signer.sign("", "https://x.example", null, 1L, "n"));
    assertThrows(IllegalArgumentException.class, () -> signer.sign("GET", null, null, 1L, "n"));
    assertThrows(
        IllegalArgumentException.class,
        () -> signer.sign("GET", "https://x.example", null, 1L, ""));
  }

  private static JsonNode loadVectors() throws Exception {
    Path[] candidates = {
      Path.of("..", "contracts", "test-vectors", "vectores.json"),
      Path.of("contracts", "test-vectors", "vectores.json")
    };
    for (Path candidate : candidates) {
      if (Files.exists(candidate)) {
        return JSON.readTree(candidate.toFile());
      }
    }
    throw new IllegalStateException("contracts/test-vectors/vectores.json was not found");
  }

  private static ECParameterSpec p256() {
    try {
      AlgorithmParameters parameters = AlgorithmParameters.getInstance("EC");
      parameters.init(new ECGenParameterSpec("secp256r1"));
      return parameters.getParameterSpec(ECParameterSpec.class);
    } catch (GeneralSecurityException exception) {
      throw new IllegalStateException("P-256 is required by the Java runtime", exception);
    }
  }

  private static PrivateKey privateKey(JsonNode jwk) throws GeneralSecurityException {
    BigInteger d = new BigInteger(1, Base64.getUrlDecoder().decode(jwk.get("d").asText()));
    return KeyFactory.getInstance("EC").generatePrivate(new ECPrivateKeySpec(d, P256));
  }

  private static ECPublicKey publicKey(JsonNode jwk) throws GeneralSecurityException {
    BigInteger x = new BigInteger(1, Base64.getUrlDecoder().decode(jwk.get("x").asText()));
    BigInteger y = new BigInteger(1, Base64.getUrlDecoder().decode(jwk.get("y").asText()));
    return (ECPublicKey)
        KeyFactory.getInstance("EC").generatePublic(new ECPublicKeySpec(new ECPoint(x, y), P256));
  }

  private static boolean verify(ECPublicKey key, String base, byte[] raw)
      throws GeneralSecurityException {
    Signature verifier = Signature.getInstance("SHA256withECDSA");
    verifier.initVerify(key);
    verifier.update(base.getBytes(StandardCharsets.UTF_8));
    return verifier.verify(rawToDer(raw));
  }

  private static byte[] rawToDer(byte[] raw) {
    byte[] r = new BigInteger(1, Arrays.copyOfRange(raw, 0, 32)).toByteArray();
    byte[] s = new BigInteger(1, Arrays.copyOfRange(raw, 32, 64)).toByteArray();
    byte[] der = new byte[6 + r.length + s.length];
    der[0] = 0x30;
    der[1] = (byte) (4 + r.length + s.length);
    der[2] = 0x02;
    der[3] = (byte) r.length;
    System.arraycopy(r, 0, der, 4, r.length);
    der[4 + r.length] = 0x02;
    der[5 + r.length] = (byte) s.length;
    System.arraycopy(s, 0, der, 6 + r.length, s.length);
    return der;
  }
}
