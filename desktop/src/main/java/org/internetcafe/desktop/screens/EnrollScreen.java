package org.internetcafe.desktop.screens;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;

public class EnrollScreen {
    private final VBox root;
    private Runnable onBack;
    private Runnable onEnrollSuccess;

    public EnrollScreen() {
        Label title = new Label("Enrolar equipo");
        title.setStyle("-fx-font-size: 26px; -fx-font-weight: 700;");

        TextField codeField = new TextField();
        codeField.setPromptText("Código de enrolamiento");

        TextField roomField = new TextField();
        roomField.setPromptText("Sala");

        HBox actions = new HBox(10);
        actions.setAlignment(Pos.CENTER);

        Button backButton = new Button("Volver");
        Button enrollButton = new Button("Enrolar");

        backButton.setOnAction(
                event -> {
                    if (onBack != null) {
                        onBack.run();
                    }
                });

        enrollButton.setOnAction(
                event -> {
                    if (onEnrollSuccess != null) {
                        onEnrollSuccess.run();
                    }
                });

        actions.getChildren().addAll(backButton, enrollButton);

        root = new VBox(16);
        root.setPadding(new Insets(32));
        root.setAlignment(Pos.CENTER);
        root.getChildren().addAll(title, codeField, roomField, actions);
    }

    public VBox getRoot() {
        return root;
    }

    public void setOnBack(Runnable onBack) {
        this.onBack = onBack;
    }

    public void setOnEnrollSuccess(Runnable onEnrollSuccess) {
        this.onEnrollSuccess = onEnrollSuccess;
    }
}
