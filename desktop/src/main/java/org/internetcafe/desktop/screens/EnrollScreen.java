package org.internetcafe.desktop.screens;

import java.util.function.Consumer;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextField;
import javafx.scene.layout.VBox;
import org.internetcafe.desktop.contract.EnrollmentResponse;

public class EnrollScreen {
  private final VBox root;
  private final TextField codeField;
  private final Button enrollButton;
  private final Label statusLabel;
  private final VBox resultBox;
  private Consumer<String> onEnroll;
  private Runnable onClose;

  public EnrollScreen() {
    Label title = new Label("Enrolar equipo");
    title.setStyle("-fx-font-size: 26px; -fx-font-weight: 700;");

    codeField = new TextField();
    codeField.setPromptText("Código de enrolamiento");
    codeField.setMaxWidth(420);

    enrollButton = new Button("Enrolar");
    enrollButton.setOnAction(
        event -> {
          if (onEnroll != null) {
            onEnroll.accept(codeField.getText());
          }
        });

    Button closeButton = new Button("Cerrar");
    closeButton.setOnAction(
        event -> {
          if (onClose != null) {
            onClose.run();
          }
        });

    statusLabel = new Label();
    statusLabel.setWrapText(true);
    resultBox = new VBox(8);
    resultBox.setAlignment(Pos.CENTER);
    resultBox.setVisible(false);
    resultBox.setManaged(false);

    root = new VBox(16, title, codeField, enrollButton, statusLabel, resultBox, closeButton);
    root.setPadding(new Insets(32));
    root.setAlignment(Pos.CENTER);
  }

  public VBox getRoot() {
    return root;
  }

  public void setOnEnroll(Consumer<String> onEnroll) {
    this.onEnroll = onEnroll;
  }

  public void setOnClose(Runnable onClose) {
    this.onClose = onClose;
  }

  public void setAvailable(boolean available, String message) {
    enrollButton.setDisable(!available);
    codeField.setDisable(!available);
    statusLabel.setText(message);
  }

  public void setBusy() {
    enrollButton.setDisable(true);
    codeField.setDisable(true);
    statusLabel.setText("Enrolando equipo...");
    resultBox.getChildren().clear();
    resultBox.setVisible(false);
    resultBox.setManaged(false);
  }

  public void showFailure(String message) {
    enrollButton.setDisable(false);
    codeField.setDisable(false);
    statusLabel.setText(message);
    resultBox.getChildren().clear();
    resultBox.setVisible(false);
    resultBox.setManaged(false);
  }

  public void showFinalFailure(String message) {
    enrollButton.setDisable(true);
    codeField.setDisable(true);
    statusLabel.setText(message);
    resultBox.getChildren().clear();
    resultBox.setVisible(false);
    resultBox.setManaged(false);
  }

  public void showSuccess(EnrollmentResponse response) {
    codeField.clear();
    enrollButton.setDisable(true);
    codeField.setDisable(true);
    statusLabel.setText("Equipo enrolado. La credencial se guardó de forma segura.");
    resultBox
        .getChildren()
        .setAll(
            new Label("Código del equipo: " + response.code()),
            new Label("Sala: " + (response.lab() == null ? "Sin asignar" : response.lab())),
            new Label("Modo: " + response.mode()),
            new Label("Identificador de clave: " + response.keyid()));
    resultBox.setVisible(true);
    resultBox.setManaged(true);
  }
}
