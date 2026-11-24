package org.internetcafe.desktop;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Verifica que {@link Main#applyApiBaseUrlArg(String[])} lee el argumento {@code
 * --api-base-url=<url>} y lo establece como propiedad del sistema {@code api.base.url}, permitiendo
 * que el script de arranque {@code Register-Startup.ps1} sobreescriba la URL embebida en el MSI.
 */
class MainApiBaseUrlArgTest {

  private static final String PROP = "api.base.url";
  private String originalProp;

  @BeforeEach
  void guardarPropOriginal() {
    originalProp = System.getProperty(PROP);
    System.clearProperty(PROP);
  }

  @AfterEach
  void restaurarPropOriginal() {
    if (originalProp != null) {
      System.setProperty(PROP, originalProp);
    } else {
      System.clearProperty(PROP);
    }
  }

  @Test
  @DisplayName("Establece api.base.url cuando se pasa --api-base-url=<url>")
  void estableceUrlCuandoSePassaElArgumento() {
    Main.applyApiBaseUrlArg(
        new String[] {"--api-base-url=https://internet-cafe-tq03.onrender.com"});
    assertEquals(
        "https://internet-cafe-tq03.onrender.com",
        System.getProperty(PROP),
        "La propiedad api.base.url debe quedar con la URL del argumento");
  }

  @Test
  @DisplayName("Usa la última ocurrencia si el argumento aparece varias veces")
  void usaLaUltimaOcurrencia() {
    Main.applyApiBaseUrlArg(
        new String[] {
          "--api-base-url=https://primera.example.com", "--api-base-url=https://segunda.example.com"
        });
    assertEquals("https://segunda.example.com", System.getProperty(PROP));
  }

  @Test
  @DisplayName("No modifica api.base.url si el argumento no está presente")
  void noModificaSiNoEstaElArgumento() {
    Main.applyApiBaseUrlArg(new String[] {"--enroll", "--otro-flag"});
    assertNull(
        System.getProperty(PROP),
        "No debe modificar la propiedad si --api-base-url no está en los argumentos");
  }

  @Test
  @DisplayName("No modifica api.base.url si el valor del argumento es vacío")
  void noModificaSiElValorEsVacio() {
    Main.applyApiBaseUrlArg(new String[] {"--api-base-url="});
    assertNull(System.getProperty(PROP), "Un valor vacío no debe establecer la propiedad");
  }

  @Test
  @DisplayName("Elimina espacios en blanco del valor de la URL")
  void eliminaEspaciosEnBlanco() {
    Main.applyApiBaseUrlArg(
        new String[] {"--api-base-url=  https://internet-cafe-tq03.onrender.com  "});
    assertEquals("https://internet-cafe-tq03.onrender.com", System.getProperty(PROP));
  }

  @Test
  @DisplayName("Tiene prioridad sobre cualquier propiedad api.base.url preexistente")
  void tieneprioridadSobrePropiedadPreexistente() {
    System.setProperty(PROP, "https://anterior.example.com");
    Main.applyApiBaseUrlArg(new String[] {"--api-base-url=https://nueva.example.com"});
    assertEquals(
        "https://nueva.example.com",
        System.getProperty(PROP),
        "El argumento debe sobreescribir la propiedad preexistente (p.ej. la del MSI)");
  }
}
