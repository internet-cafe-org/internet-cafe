package org.internetcafe.desktop.identity;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.attribute.AclEntryPermission;
import java.nio.file.attribute.AclFileAttributeView;
import java.security.MessageDigest;
import java.util.Base64;
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
      assertTrue(
          aclView.getAcl().stream()
              .anyMatch(
                  entry ->
                      entry.principal().getName().contains("Users")
                          && entry.permissions().contains(AclEntryPermission.READ_DATA)
                          && !entry.permissions().contains(AclEntryPermission.WRITE_DATA)));
    }
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
