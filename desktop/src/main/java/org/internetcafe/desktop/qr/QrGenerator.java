package org.internetcafe.desktop.qr;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.EncodeHintType;
import com.google.zxing.WriterException;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel;
import java.util.Map;

/** Genera códigos QR con ZXing. */
public final class QrGenerator {

  private QrGenerator() {}

  /**
   * Genera un QR cuadrado.
   *
   * @param content texto que irá dentro del QR
   * @param size lado del QR en píxeles
   * @return matriz de bits del QR (true = módulo oscuro)
   */
  public static BitMatrix generate(String content, int size) {
    if (content == null || content.isBlank()) {
      throw new IllegalArgumentException("El contenido del QR no puede estar vacío");
    }
    if (size <= 0) {
      throw new IllegalArgumentException("El tamaño del QR debe ser mayor que cero");
    }
    Map<EncodeHintType, Object> hints =
        Map.of(EncodeHintType.ERROR_CORRECTION, ErrorCorrectionLevel.M, EncodeHintType.MARGIN, 1);
    try {
      return new QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, size, size, hints);
    } catch (WriterException e) {
      // No se incluye el contenido en el mensaje para no filtrar datos en los logs.
      throw new IllegalStateException("No se pudo generar el QR", e);
    }
  }
}
