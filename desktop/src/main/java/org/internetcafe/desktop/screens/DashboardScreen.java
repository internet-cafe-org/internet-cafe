package org.internetcafe.desktop.screens;

import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.VBox;

public class DashboardScreen {
    private final VBox root;
    private final Label statusLabel;
    private Runnable onLogout;

    public DashboardScreen() {
        Label title = new Label("Panel del equipo");
        title.setStyle("-fx-font-size: 28px; -fx-font-weight: 700;");

        statusLabel = new Label("Sin sesión activa");
        statusLabel.setStyle("-fx-font-size: 18px;");

        Button logoutButton = new Button("Cerrar sesión");
        logoutButton.setOnAction(
                event -> {
                    if (onLogout != null) {
                        onLogout.run();
                    }
                });

        root = new VBox(16);
        root.setPadding(new Insets(32));
        root.setAlignment(Pos.CENTER);
        root.getChildren().addAll(title, statusLabel, logoutButton);
    }

    public VBox getRoot() {
        return root;
    }

    public void setStatus(String status) {
        statusLabel.setText(status);
    }

    public void setOnLogout(Runnable onLogout) {
        this.onLogout = onLogout;
    }
}
