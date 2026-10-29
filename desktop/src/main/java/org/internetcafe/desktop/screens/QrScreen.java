package org.internetcafe.desktop.screens;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.VBox;

public class QrScreen {
    private final VBox root;
    private Runnable onBack;

    public QrScreen() {
        Label title = new Label("QR de acceso");
        title.setStyle("-fx-font-size: 26px; -fx-font-weight: 700;");

        Label qrPlaceholder = new Label("Código QR");
        qrPlaceholder.setStyle(
                "-fx-font-size: 22px; -fx-border-color: #7c7c7c; -fx-border-width: 2; -fx-padding: 80 120; -fx-background-color: white;");

        Button backButton = new Button("Volver");

        backButton.setOnAction(
                event -> {
                    if (onBack != null) {
                        onBack.run();
                    }
                });

        root = new VBox(18);
        root.setPadding(new Insets(32));
        root.setAlignment(Pos.CENTER);
        root.getChildren().addAll(title, qrPlaceholder, backButton);
    }

    public VBox getRoot() {
        return root;
    }

    public void setOnBack(Runnable onBack) {
        this.onBack = onBack;
    }
}
