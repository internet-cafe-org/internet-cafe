package org.internetcafe.desktop.identity;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class ProtectedEnrollmentStoreTest {
  private static final SecretProtector TEST_PROTECTOR =
      new SecretProtector() {
        @Override
        public byte[] protect(byte[] plaintext) {
          return transform(plaintext);
        }

        @Override
        public byte[] unprotect(byte[] ciphertext) {
          return transform(ciphertext);
        }

        private byte[] transform(byte[] input) {
          byte[] result = input.clone();
          for (int index = 0; index < result.length; index++) {
            result[index] ^= 0x5a;
          }
          return result;
        }
      };

  @TempDir java.nio.file.Path temporaryDirectory;

  @Test
  void savesAndReloadsEnrollmentWithoutWritingItInPlaintext() throws Exception {
    var file = new ProtectedFile(temporaryDirectory.resolve("enrollment.bin"), TEST_PROTECTOR);
    var store = new EnrollmentStore(file);
    var response =
        new EnrollmentResponse("machine-id", "LAB1-PC03", "Sala 1", "kiosk", "keyid-placeholder");

    store.save(response);

    assertEquals(response, store.load());
    assertFalse(
        new String(
                Files.readAllBytes(temporaryDirectory.resolve("enrollment.bin")),
                StandardCharsets.UTF_8)
            .contains(response.keyid()));
  }

  @Test
  void loadsEnrollmentFilesThatStillHoldTheRetiredCredential() throws Exception {
    var file = new ProtectedFile(temporaryDirectory.resolve("enrollment.bin"), TEST_PROTECTOR);
    file.write(
        ("{\"machine_id\":\"machine-id\",\"code\":\"LAB1-PC03\",\"lab\":\"Sala 1\","
                + "\"mode\":\"kiosk\",\"keyid\":\"keyid-placeholder\","
                + "\"provisional_credential\":\"retired\"}")
            .getBytes(StandardCharsets.UTF_8));

    assertEquals(
        new EnrollmentResponse("machine-id", "LAB1-PC03", "Sala 1", "kiosk", "keyid-placeholder"),
        new EnrollmentStore(file).load());
  }

  @Test
  void createsAndReloadsMachineIdentityPasswordWithoutPlaintextPersistence() throws Exception {
    var path = temporaryDirectory.resolve("machine-identity-password.bin");
    var store = new MachineIdentityPasswordStore(new ProtectedFile(path, TEST_PROTECTOR));

    char[] first = store.loadOrCreate();
    char[] second = store.loadExisting();

    assertArrayEquals(first, second);
    assertFalse(
        new String(Files.readAllBytes(path), StandardCharsets.US_ASCII)
            .contains(new String(first)));
    Arrays.fill(first, '\0');
    Arrays.fill(second, '\0');
  }

  @Test
  void loadingPasswordRequiresExistingProtectedData() {
    var path = temporaryDirectory.resolve("missing-password.bin");
    var store = new MachineIdentityPasswordStore(new ProtectedFile(path, TEST_PROTECTOR));

    assertThrows(java.nio.file.NoSuchFileException.class, store::loadExisting);
    assertFalse(Files.exists(path));
  }

  @Test
  void protectedPasswordOpensTheSameMachineIdentityAfterReload() throws Exception {
    var passwordFile =
        new ProtectedFile(
            temporaryDirectory.resolve("machine-identity-password.bin"), TEST_PROTECTOR);
    var passwordStore = new MachineIdentityPasswordStore(passwordFile);
    char[] firstPassword = passwordStore.loadOrCreate();
    MachineIdentity created =
        new MachineIdentityStore(temporaryDirectory.resolve("identity"), firstPassword)
            .loadOrCreate();
    Arrays.fill(firstPassword, '\0');

    char[] reloadedPassword = passwordStore.loadOrCreate();
    MachineIdentity loaded =
        new MachineIdentityStore(temporaryDirectory.resolve("identity"), reloadedPassword)
            .loadExisting();

    assertEquals(created.publicJwk(), loaded.publicJwk());
    assertEquals(created.thumbprint(), loaded.thumbprint());
    Arrays.fill(reloadedPassword, '\0');
  }

  @Test
  void windowsDpapiProtectsAndUnprotectsForTheCurrentAccount() throws Exception {
    assumeTrue(System.getProperty("os.name", "").startsWith("Windows"));
    byte[] secret = "local-secret".getBytes(StandardCharsets.UTF_8);
    WindowsDpapiProtector protector = new WindowsDpapiProtector();

    byte[] protectedData = protector.protect(secret);

    assertFalse(Arrays.equals(secret, protectedData));
    assertArrayEquals(secret, protector.unprotect(protectedData));
  }
}
