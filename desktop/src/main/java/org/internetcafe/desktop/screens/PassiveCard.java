package org.internetcafe.desktop.screens;

import java.net.URL;
import javafx.geometry.Rectangle2D;
import javafx.scene.Scene;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.VBox;
import javafx.scene.paint.Color;
import javafx.stage.Screen;
import javafx.stage.Stage;
import javafx.stage.StageStyle;

/**
 * Floating card shown in the bottom-right corner while the machine is in passive mode: machine
 * label, title, status and the "Registrar acceso" button.
 */
public class PassiveCard {

  private static final double WIDTH_PX = 300;
  private static final double MARGIN_PX = 16;

  private final Stage stage;
  private final Label machineLabel;
  private final Label statusLabel;
  private Runnable onRegister;

  public PassiveCard() {
    machineLabel = new Label();
    machineLabel.getStyleClass().add("passive-machine");

    Label title = new Label("Equipo en modo pasivo");
    title.getStyleClass().add("passive-title");
    title.setWrapText(true);

    statusLabel = new Label();
    statusLabel.getStyleClass().add("passive-status");
    statusLabel.setWrapText(true);

    Button registerButton = new Button("Registrar acceso");
    registerButton.getStyleClass().add("passive-register");
    registerButton.setMaxWidth(Double.MAX_VALUE);
    registerButton.setDefaultButton(true);
    registerButton.setOnAction(
        event -> {
          if (onRegister != null) {
            onRegister.run();
          }
        });

    VBox card = new VBox(12, machineLabel, title, statusLabel, registerButton);
    card.getStyleClass().add("passive-card");
    card.setPrefWidth(WIDTH_PX);

    Scene scene = new Scene(card);
    scene.setFill(Color.TRANSPARENT);
    URL css = getClass().getResource("/passive.css");
    if (css != null) {
      scene.getStylesheets().add(css.toExternalForm());
    }

    stage = new Stage(StageStyle.TRANSPARENT);
    stage.setTitle("Internet Caf\u00e9 - modo pasivo");
    stage.setScene(scene);
    stage.setResizable(false);
  }

  /** Called on the JavaFX thread when the person presses "Registrar acceso". */
  public void setOnRegister(Runnable onRegister) {
    this.onRegister = onRegister;
  }

  /** Shows the card (or brings it to the front) in the bottom-right corner of the screen. */
  public void show(String machine, String status) {
    machineLabel.setText(machine);
    statusLabel.setText(status);
    stage.show();
    Rectangle2D bounds = Screen.getPrimary().getVisualBounds();
    stage.setX(bounds.getMaxX() - stage.getWidth() - MARGIN_PX);
    stage.setY(bounds.getMaxY() - stage.getHeight() - MARGIN_PX);
    stage.toFront();
  }

  public void hide() {
    stage.hide();
  }
}