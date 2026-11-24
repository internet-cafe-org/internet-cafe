package org.internetcafe.desktop.identity;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.attribute.AclEntryPermission;
import java.nio.file.attribute.AclEntryType;
import java.nio.file.attribute.AclFileAttributeView;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.Set;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class MachineIdentityStoreTest {
  private static final char[] PASSWORD = "test-only-password".toCharArray();

  @TempDir java.nio.file.Path tempDirectory;

  @Test
  void createsAndReloadsP256IdentityFromPkcs12() throws Exception {
    MachineIdentityStore store = new MachineIdentityStore(tempDirectory, PASSWORD);

    MachineIdentity created = store.loadOrCreate();
    MachineIdentity loaded = store.loadOrCreate();

    assertEquals("EC", created.publicJwk().kty());
    assertEquals("P-256", created.publicJwk().crv());
    assertEquals(32, Base64.getUrlDecoder().decode(created.publicJwk().x()).length);
    assertEquals(32, Base64.getUrlDecoder().decode(created.publicJwk().y()).length);
    assertEquals(created.publicJwk(), loaded.publicJwk());
    assertEquals(created.thumbprint(), loaded.thumbprint());
    assertTrue(created.publicJwk().matchesThumbprint(loaded.thumbprint()));
    assertEquals(
        Base64.getUrlEncoder()
            .withoutPadding()
            .encodeToString(
                MessageDigest.getInstance("SHA-256")
                    .digest(
                        ("{\"crv\":\"P-256\",\"kty\":\"EC\",\"x\":\""
                                + created.publicJwk().x()
                                + "\",\"y\":\""
                                + created.publicJwk().y()
                                + "\"}")
                            .getBytes(StandardCharsets.UTF_8))),
        created.thumbprint());
    assertFalse(created.publicJwk().toJson().contains("\"d\""));
    assertNotNull(created.privateKey());
    assertNotNull(created.certificate());
    created.certificate().verify(created.publicKey());
    assertEquals(
        created.certificate().getSubjectX500Principal(),
        created.certificate().getIssuerX500Principal());
    var keyStorePath = tempDirectory.resolve("machine-identity.p12");
    assertTrue(Files.exists(keyStorePath));
    if (System.getProperty("os.name", "").startsWith("Windows")) {
      AclFileAttributeView aclView =
          Files.getFileAttributeView(keyStorePath, AclFileAttributeView.class);
      assertNotNull(aclView);
      // Resuelve por SID el grupo real que debe tener solo lectura: Users (S-1-5-32-545)
      // o, como alternativa, Authenticated Users (S-1-5-11).
      var users = com.sun.jna.platform.win32.Advapi32Util.getAccountBySid("S-1-5-32-545");
      var authenticated = com.sun.jna.platform.win32.Advapi32Util.getAccountBySid("S-1-5-11");
      Set<String> expectedNames =
          Set.of(
              (users.domain + "\\" + users.name).toLowerCase(),
              (authenticated.domain + "\\" + authenticated.name).toLowerCase());

      assertTrue(
          aclView.getAcl().stream()
              .anyMatch(
                  entry ->
                      entry.type() == AclEntryType.ALLOW
                          && entry.permissions().contains(AclEntryPermission.READ_DATA)
                          && !entry.permissions().contains(AclEntryPermission.WRITE_DATA)
                          && expectedNames.contains(entry.principal().getName().toLowerCase())),
          "El ACL del keystore debe dar solo lectura al grupo Users (o Authenticated Users)");
    }
  }

  @Test
  void loadsOnlyAnExistingIdentityWithoutCreatingOne() throws Exception {
    MachineIdentityStore store = new MachineIdentityStore(tempDirectory, PASSWORD);

    assertThrows(java.nio.file.NoSuchFileException.class, store::loadExisting);

    MachineIdentity created = store.loadOrCreate();
    assertEquals(created.publicJwk(), store.loadExisting().publicJwk());
  }

  @Test
  void rejectsNonMatchingLocalThumbprint() throws Exception {
    MachineIdentity identity = new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate();

    assertFalse(identity.publicJwk().matchesThumbprint("not-a-thumbprint"));
    assertFalse(identity.publicJwk().matchesThumbprint(null));
  }

  @Test
  void concurrentCreationKeepsThePersistedIdentity() throws Exception {
    try (var executor = Executors.newFixedThreadPool(4)) {
      var first =
          executor.submit(() -> new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate());
      var second =
          executor.submit(() -> new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate());
      var third =
          executor.submit(() -> new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate());
      var fourth =
          executor.submit(() -> new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate());

      String thumbprint = first.get().thumbprint();
      assertEquals(thumbprint, second.get().thumbprint());
      assertEquals(thumbprint, third.get().thumbprint());
      assertEquals(thumbprint, fourth.get().thumbprint());
    }
  }

  @Test
  void doesNotReplaceAnUnreadableKeystore() throws Exception {
    Files.createDirectories(tempDirectory);
    Files.writeString(tempDirectory.resolve("machine-identity.p12"), "not a keystore");

    assertThrows(
        java.io.IOException.class,
        () -> new MachineIdentityStore(tempDirectory, PASSWORD).loadOrCreate());
    assertEquals("not a keystore", Files.readString(tempDirectory.resolve("machine-identity.p12")));
  }

  @Test
  void rejectsJwkWithInvalidCoordinates() {
    assertThrows(IllegalArgumentException.class, () -> new PublicJwk("EC", "P-256", "abc", "abc"));
  }
}
