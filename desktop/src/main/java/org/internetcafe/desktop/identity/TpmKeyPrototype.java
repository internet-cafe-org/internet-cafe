package org.internetcafe.desktop.identity;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.security.Key;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.cert.Certificate;
import java.util.Locale;

/**
 * Prototipo ST-DSK-01: firmar con una clave que vive en el TPM de Windows y no se puede exportar,
 * usando solo el proveedor SunMSCAPI del JDK (almacen {@code Windows-MY}). La clave se crea fuera
 * de Java (ver docs/desktop/ST-DSK-01-tpm-sunmscapi.md); aqui solo se busca por alias y se usa.
 */
public final class TpmKeyPrototype {

  static final String WINDOWS_KEYSTORE = "Windows-MY";

  /** Firma y proveedor JCA que la produjo. */
  public record Signed(byte[] signature, String provider) {}

  private TpmKeyPrototype() {}

  /** True si el sistema operativo es Windows (SunMSCAPI solo existe alli). */
  public static boolean isWindows() {
    return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
  }

  /** Abre el almacen de certificados del usuario de Windows. */
  public static KeyStore openWindowsStore() throws GeneralSecurityException, IOException {
    if (!isWindows()) {
      throw new UnsupportedOperationException("SunMSCAPI solo esta disponible en Windows");
    }
    KeyStore store = KeyStore.getInstance(WINDOWS_KEYSTORE);
    store.load(null, null);
    return store;
  }

  public static PrivateKey privateKey(KeyStore store, String alias)
      throws GeneralSecurityException {
    Key key = store.getKey(alias, null);
    if (key instanceof PrivateKey privateKey) {
      return privateKey;
    }
    throw new KeyStoreException("No hay clave privada para el alias indicado");
  }

  public static PublicKey publicKey(KeyStore store, String alias) throws KeyStoreException {
    Certificate certificate = store.getCertificate(alias);
    if (certificate == null) {
      throw new KeyStoreException("No hay certificado para el alias indicado");
    }
    return certificate.getPublicKey();
  }

  /** Una clave no exportable no entrega su material: {@code getEncoded()} devuelve null. */
  public static boolean isNonExportable(PrivateKey key) {
    return key.getEncoded() == null;
  }

  /** Algoritmo de firma segun el tipo de clave (EC o RSA). */
  public static String signatureAlgorithm(String keyAlgorithm) {
    return switch (keyAlgorithm) {
      case "EC", "ECDSA" -> "SHA256withECDSA";
      case "RSA" -> "SHA256withRSA";
      default -> throw new IllegalArgumentException("Algoritmo de clave no soportado");
    };
  }

  public static Signed sign(PrivateKey key, byte[] data) throws GeneralSecurityException {
    Signature signature = Signature.getInstance(signatureAlgorithm(key.getAlgorithm()));
    signature.initSign(key);
    signature.update(data);
    byte[] bytes = signature.sign();
    return new Signed(bytes, signature.getProvider().getName());
  }

  public static boolean verify(PublicKey key, byte[] data, byte[] signatureBytes)
      throws GeneralSecurityException {
    Signature signature = Signature.getInstance(signatureAlgorithm(key.getAlgorithm()));
    signature.initVerify(key);
    signature.update(data);
    return signature.verify(signatureBytes);
  }
}
