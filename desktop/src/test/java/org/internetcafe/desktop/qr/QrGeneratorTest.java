package org.internetcafe.desktop.qr;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.google.zxing.common.BitMatrix;
import org.junit.jupiter.api.Test;

class QrGeneratorTest {

  @Test
  void generatesSquareMatrixWithRequestedSize() {
    BitMatrix matrix = QrGenerator.generate("contenido-de-prueba", 200);

    assertEquals(200, matrix.getWidth());
    assertEquals(200, matrix.getHeight());
  }

  @Test
  void rejectsBlankContent() {
    assertThrows(IllegalArgumentException.class, () -> QrGenerator.generate("  ", 200));
  }

  @Test
  void rejectsNonPositiveSize() {
    assertThrows(IllegalArgumentException.class, () -> QrGenerator.generate("abc", 0));
  }
}
