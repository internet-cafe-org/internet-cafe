package org.internetcafe.desktop.identity;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.AclEntry;
import java.nio.file.attribute.AclEntryFlag;
import java.nio.file.attribute.AclEntryPermission;
import java.nio.file.attribute.AclEntryType;
import java.nio.file.attribute.AclFileAttributeView;
import java.nio.file.attribute.UserPrincipalNotFoundException;
import java.security.GeneralSecurityException;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.security.spec.ECGenParameterSpec;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Date;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.logging.Logger;
import org.bouncycastle.asn1.x500.X500Name;
import org.bouncycastle.asn1.x509.BasicConstraints;
import org.bouncycastle.asn1.x509.Extension;
import org.bouncycastle.asn1.x509.KeyUsage;
import org.bouncycastle.cert.X509CertificateHolder;
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter;
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder;
import org.bouncycastle.operator.ContentSigner;
import org.bouncycastle.operator.OperatorCreationException;
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder;

public final class MachineIdentityStore {
  private static final Logger LOGGER = Logger.getLogger(MachineIdentityStore.class.getName());
  private static final String KEYSTORE_TYPE = "PKCS12";
  private static final String KEY_ALIAS = "machine-key";
  private static final String STORE_FILENAME = "machine-identity.p12";
  private static final String CERTIFICATE_SUBJECT = "CN=Internet Cafe Machine";

  private final Path directory;
  private final Path keyStorePath;
  private final char[] password;

  public MachineIdentityStore(Path directory, char[] password) {
    if (directory == null || password == null || password.length == 0) {
      throw new IllegalArgumentException("Directory and keystore password are required");
    }
    this.directory = directory.toAbsolutePath().normalize();
    this.keyStorePath = this.directory.resolve(STORE_FILENAME);
    this.password = password.clone();
  }

  public static MachineIdentityStore underProgramData(char[] password) throws IOException {
    String programData = System.getenv("ProgramData");
    if (programData == null || programData.isBlank()) {
      throw new IOException("The ProgramData environment variable is not available");
    }
    return new MachineIdentityStore(Path.of(programData, "InternetCafe"), password);
  }

  public MachineIdentity loadOrCreate() throws IOException, GeneralSecurityException {
    Files.createDirectories(directory);
    applyAcl(directory, true);
    if (Files.exists(keyStorePath)) {
      applyAcl(keyStorePath, false);
      return load();
    }

    KeyPair keyPair = generateKeyPair();
    var certificate = createCertificate(keyPair);
    KeyStore keyStore = KeyStore.getInstance(KEYSTORE_TYPE);
    keyStore.load(null, password);
    keyStore.setKeyEntry(
        KEY_ALIAS,
        keyPair.getPrivate(),
        password,
        new java.security.cert.Certificate[] {certificate});

    byte[] serializedKeyStore;
    try (ByteArrayOutputStream output = new ByteArrayOutputStream()) {
      keyStore.store(output, password);
      serializedKeyStore = output.toByteArray();
    }

    Path temporaryFile = Files.createTempFile(directory, "machine-identity-", ".tmp");
    try {
      applyAcl(temporaryFile, false);
      Files.write(temporaryFile, serializedKeyStore);
      try {
        Files.move(temporaryFile, keyStorePath);
      } catch (FileAlreadyExistsException exception) {
        return load();
      }
    } finally {
      Files.deleteIfExists(temporaryFile);
    }

    applyAcl(keyStorePath, false);
    return toIdentity(keyPair.getPrivate(), certificate);
  }

  private MachineIdentity load() throws IOException, GeneralSecurityException {
    KeyStore keyStore = KeyStore.getInstance(KEYSTORE_TYPE);
    try (var input = Files.newInputStream(keyStorePath)) {
      keyStore.load(input, password);
    }
    if (!keyStore.isKeyEntry(KEY_ALIAS)) {
      throw new GeneralSecurityException("Machine keystore does not contain its identity key");
    }

    var privateKey = (java.security.PrivateKey) keyStore.getKey(KEY_ALIAS, password);
    var certificate = (java.security.cert.X509Certificate) keyStore.getCertificate(KEY_ALIAS);
    if (privateKey == null || certificate == null || !"EC".equals(privateKey.getAlgorithm())) {
      throw new GeneralSecurityException("Machine keystore contains an invalid identity");
    }
    certificate.checkValidity();
    certificate.verify(certificate.getPublicKey());
    if (!(certificate.getPublicKey() instanceof ECPublicKey publicKey)
        || !PublicJwk.isP256(publicKey.getParams())) {
      throw new GeneralSecurityException("Machine keystore identity is not P-256");
    }
    verifyKeyPair(privateKey, publicKey);
    return toIdentity(privateKey, certificate);
  }

  private static KeyPair generateKeyPair() throws GeneralSecurityException {
    KeyPairGenerator generator = KeyPairGenerator.getInstance("EC");
    generator.initialize(new ECGenParameterSpec("secp256r1"), new SecureRandom());
    return generator.generateKeyPair();
  }

  private static java.security.cert.X509Certificate createCertificate(KeyPair keyPair)
      throws GeneralSecurityException, IOException {
    Instant now = Instant.now();
    X500Name subject = new X500Name(CERTIFICATE_SUBJECT);
    var builder =
        new JcaX509v3CertificateBuilder(
            subject,
            new BigInteger(159, new SecureRandom()).add(BigInteger.ONE),
            Date.from(now.minus(1, ChronoUnit.MINUTES)),
            Date.from(now.plus(3650, ChronoUnit.DAYS)),
            subject,
            keyPair.getPublic());
    builder.addExtension(Extension.basicConstraints, true, new BasicConstraints(false));
    builder.addExtension(Extension.keyUsage, true, new KeyUsage(KeyUsage.digitalSignature));
    ContentSigner signer;
    try {
      signer = new JcaContentSignerBuilder("SHA256withECDSA").build(keyPair.getPrivate());
    } catch (OperatorCreationException exception) {
      throw new GeneralSecurityException(
          "Unable to create machine identity certificate", exception);
    }
    X509CertificateHolder certificateHolder = builder.build(signer);
    return new JcaX509CertificateConverter().getCertificate(certificateHolder);
  }

  private static void verifyKeyPair(
      java.security.PrivateKey privateKey, java.security.PublicKey publicKey)
      throws GeneralSecurityException {
    byte[] challenge = new byte[32];
    new SecureRandom().nextBytes(challenge);
    Signature signer = Signature.getInstance("SHA256withECDSA");
    signer.initSign(privateKey);
    signer.update(challenge);
    byte[] signature = signer.sign();

    Signature verifier = Signature.getInstance("SHA256withECDSA");
    verifier.initVerify(publicKey);
    verifier.update(challenge);
    if (!verifier.verify(signature)) {
      throw new GeneralSecurityException("Machine keystore certificate does not match its key");
    }
  }

  private static MachineIdentity toIdentity(
      java.security.PrivateKey privateKey, java.security.cert.X509Certificate certificate)
      throws GeneralSecurityException {
    if (!(certificate.getPublicKey() instanceof ECPublicKey publicKey)) {
      throw new GeneralSecurityException("Machine identity certificate does not contain an EC key");
    }
    PublicJwk jwk = PublicJwk.from(publicKey);
    return new MachineIdentity(privateKey, publicKey, certificate, jwk, jwk.thumbprint());
  }

  private static void applyAcl(Path path, boolean directory) throws IOException {
    if (!System.getProperty("os.name", "").startsWith("Windows")) {
      return;
    }
    AclFileAttributeView aclView = Files.getFileAttributeView(path, AclFileAttributeView.class);
    if (aclView == null) {
      throw new IOException("The machine identity path does not support Windows ACLs");
    }

    List<AclEntry> entries = new ArrayList<>();
    entries.add(allow(Files.getOwner(path), directory));
    var lookup = path.getFileSystem().getUserPrincipalLookupService();
    entries.add(allow(lookup.lookupPrincipalByName("NT AUTHORITY\\SYSTEM"), directory));
    var users = resolveRuntimeUsers(lookup, directory);
    entries.add(readOnly(users, directory));
    try {
      entries.add(allow(lookup.lookupPrincipalByName("BUILTIN\\Administrators"), directory));
    } catch (UserPrincipalNotFoundException exception) {
      if (directory) {
        LOGGER.warning(
            "Windows Administrators group could not be resolved; machine identity ACL excludes that"
                + " group");
      }
    }
    aclView.setAcl(entries);
  }

  private static java.nio.file.attribute.UserPrincipal resolveRuntimeUsers(
      java.nio.file.attribute.UserPrincipalLookupService lookup, boolean directory)
      throws IOException {
    try {
      return lookup.lookupPrincipalByName("BUILTIN\\Users");
    } catch (UserPrincipalNotFoundException exception) {
      try {
        var authenticatedUsers = lookup.lookupPrincipalByName("NT AUTHORITY\\Authenticated Users");
        if (directory) {
          LOGGER.warning(
              "Windows Users group could not be resolved; read-only access is granted to"
                  + " Authenticated Users instead");
        }
        return authenticatedUsers;
      } catch (UserPrincipalNotFoundException fallbackException) {
        throw new IOException(
            "Unable to resolve a Windows group for read-only machine identity access",
            fallbackException);
      }
    }
  }

  private static AclEntry readOnly(
      java.nio.file.attribute.UserPrincipal principal, boolean directory) {
    Set<AclEntryPermission> permissions =
        directory
            ? EnumSet.of(
                AclEntryPermission.EXECUTE,
                AclEntryPermission.LIST_DIRECTORY,
                AclEntryPermission.READ_ACL,
                AclEntryPermission.READ_ATTRIBUTES,
                AclEntryPermission.READ_NAMED_ATTRS,
                AclEntryPermission.SYNCHRONIZE)
            : EnumSet.of(
                AclEntryPermission.READ_ACL,
                AclEntryPermission.READ_ATTRIBUTES,
                AclEntryPermission.READ_DATA,
                AclEntryPermission.READ_NAMED_ATTRS,
                AclEntryPermission.SYNCHRONIZE);
    Set<AclEntryFlag> flags =
        directory
            ? EnumSet.of(AclEntryFlag.DIRECTORY_INHERIT, AclEntryFlag.FILE_INHERIT)
            : EnumSet.noneOf(AclEntryFlag.class);
    return AclEntry.newBuilder()
        .setType(AclEntryType.ALLOW)
        .setPrincipal(principal)
        .setPermissions(permissions)
        .setFlags(flags)
        .build();
  }

  private static AclEntry allow(
      java.nio.file.attribute.UserPrincipal principal, boolean directory) {
    Set<AclEntryFlag> flags =
        directory
            ? EnumSet.of(AclEntryFlag.DIRECTORY_INHERIT, AclEntryFlag.FILE_INHERIT)
            : EnumSet.noneOf(AclEntryFlag.class);
    return AclEntry.newBuilder()
        .setType(AclEntryType.ALLOW)
        .setPrincipal(principal)
        .setPermissions(EnumSet.allOf(AclEntryPermission.class))
        .setFlags(flags)
        .build();
  }
}
