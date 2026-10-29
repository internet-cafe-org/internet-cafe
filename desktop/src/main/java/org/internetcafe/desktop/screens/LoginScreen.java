package org.internetcafe.desktop.screens;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.PasswordField;
import javafx.scene.control.TextField;
import javafx.scene.layout.VBox;

public class LoginScreen {
    private final VBox root;
    private Runnable onLoginSuccess;
    private Runnable onEnroll;

    public LoginScreen() {
        Label title = new Label("Internet Cafe");
        title.setStyle("-fx-font-size: 28px; -fx-font-weight: 700;");

        TextField emailField = new TextField();
        emailField.setPromptText("Correo institucional");

        PasswordField passwordField = new PasswordField();
        passwordField.setPromptText("Contraseña");

        Button loginButton = new Button("Entrar");
        Button enrollButton = new Button("Enrolar equipo");

        loginButton.setOnAction(
                event -> {
                    if (onLoginSuccess != null) {
                        onLoginSuccess.run();
                    }
                });

        enrollButton.setOnAction(
                event -> {
                    if (onEnroll != null) {
                        onEnroll.run();
                    }
                });

        root = new VBox(14);
        root.setPadding(new Insets(32));
        root.setAlignment(Pos.CENTER);
        root.getChildren().addAll(title, emailField, passwordField, loginButton, enrollButton);
    }

    public VBox getRoot() {
        return root;
    }

    public void setOnLoginSuccess(Runnable onLoginSuccess) {
        this.onLoginSuccess = onLoginSuccess;
    }

    public void setOnEnroll(Runnable onEnroll) {
        this.onEnroll = onEnroll;
    }
}
