package org.internetcafe.desktop.identity;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeFalse;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.spec.ECGenParameterSpec;
import org.junit.jupiter.api.Test;

class TpmKeyPrototypeTest {

  private static final byte[] CHALLENGE = "reto-de-prueba".getBytes(StandardCharsets.UTF_8);

  private static KeyPair softwareEcKeyPair() throws Exception {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"));
    return generator.generateKeyPair();
  }

  @Test
  void signsAndVerifiesWithASoftwareEcKey() throws Exception {
    KeyPair pair = softwareEcKeyPair();
    TpmKeyPrototype.Signed signed = TpmKeyPrototype.sign(pair.getPrivate(), CHALLENGE);
    assertFalse(signed.provider().isBlank());
    assertTrue(TpmKeyPrototype.verify(pair.getPublic(), CHALLENGE, signed.signature()));
    byte[] tampered = "otro-reto".getBytes(StandardCharsets.UTF_8);
    assertFalse(TpmKeyPrototype.verify(pair.getPublic(), tampered, signed.signature()));
  }

  @Test
  void aSoftwareKeyIsExportable() throws Exception {
    assertFalse(TpmKeyPrototype.isNonExportable(softwareEcKeyPair().getPrivate()));
  }

  @Test
  void pickSignatureAlgorithmByKeyType() {
    assertEquals("SHA256withECDSA", TpmKeyPrototype.signatureAlgorithm("EC"));
    assertEquals("SHA256withRSA", TpmKeyPrototype.signatureAlgorithm("RSA"));
    assertThrows(IllegalArgumentException.class, () -> TpmKeyPrototype.signatureAlgorithm("DSA"));
  }

  @Test
  void windowsStoreIsRejectedOutsideWindows() {
    assumeFalse(TpmKeyPrototype.isWindows());
    assertThrows(UnsupportedOperationException.class, TpmKeyPrototype::openWindowsStore);
  }

  /**
   * Prueba real con la clave del TPM. Solo corre en Windows con la variable de entorno TPM_ALIAS
   * (alias de la clave creada con New-SelfSignedCertificate). En CI se omite.
   */
  @Test
  void signsWithTheRealWindowsKey() throws Exception {
    String alias = System.getenv("TPM_ALIAS");
    assumeTrue(TpmKeyPrototype.isWindows() && alias != null && !alias.isBlank());

    KeyStore store = TpmKeyPrototype.openWindowsStore();
    PrivateKey key = TpmKeyPrototype.privateKey(store, alias);
    PublicKey publicKey = TpmKeyPrototype.publicKey(store, alias);

    TpmKeyPrototype.Signed signed = TpmKeyPrototype.sign(key, CHALLENGE);
    boolean verified = TpmKeyPrototype.verify(publicKey, CHALLENGE, signed.signature());

    int rounds = 10;
    long start = System.nanoTime();
    for (int i = 0; i < rounds; i++) {
      TpmKeyPrototype.sign(key, CHALLENGE);
    }
    long averageMs = (System.nanoTime() - start) / rounds / 1_000_000L;

    System.out.println("TPM-PROTO tipo_de_clave=" + key.getAlgorithm());
    System.out.println("TPM-PROTO clase_de_clave=" + key.getClass().getName());
    System.out.println("TPM-PROTO no_exportable=" + TpmKeyPrototype.isNonExportable(key));
    System.out.println("TPM-PROTO proveedor_de_firma=" + signed.provider());
    System.out.println("TPM-PROTO firma_bytes=" + signed.signature().length);
    System.out.println("TPM-PROTO firma_verificada=" + verified);
    System.out.println("TPM-PROTO promedio_ms_por_firma=" + averageMs);

    assertTrue(verified);
    assertTrue(TpmKeyPrototype.isNonExportable(key));
  }
}
