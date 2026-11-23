module org.internetcafe.desktop {
    requires javafx.controls;
    requires javafx.fxml;
    requires java.net.http;
    requires java.desktop;
    requires java.logging;
    requires java.security.jgss;

    // Jackson (automáticos — no tienen module-info, se exponen como automatic modules)
    requires com.fasterxml.jackson.databind;
    requires com.fasterxml.jackson.annotation;
    requires com.fasterxml.jackson.core;

    // ZXing QR
    requires com.google.zxing;
    requires com.google.zxing.javase;

    // BouncyCastle
    requires org.bouncycastle.pkix;
    requires org.bouncycastle.provider;

    // JNA (lectura del registro de Windows, DPAPI)
    requires com.sun.jna;
    requires com.sun.jna.platform;

    // Abre el paquete principal a JavaFX para reflexión (FXML, Application)
    exports org.internetcafe.desktop;
    exports org.internetcafe.desktop.screens;
    exports org.internetcafe.desktop.contract;
    exports org.internetcafe.desktop.services;
    exports org.internetcafe.desktop.identity;
    exports org.internetcafe.desktop.qr;
    exports org.internetcafe.desktop.signing;

    opens org.internetcafe.desktop to javafx.graphics;
    opens org.internetcafe.desktop.screens to javafx.graphics, javafx.fxml;
}
