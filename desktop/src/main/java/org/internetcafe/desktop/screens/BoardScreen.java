package org.internetcafe.desktop.screens;

import java.time.Clock;
import java.time.Instant;
import java.util.logging.Logger;
import javafx.animation.KeyFrame;
import javafx.animation.Timeline;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;

/**
 * Pantalla del tablero b\u00e1sico (DSK-06): nombre, c\u00f3digo enmascarado, hora de inicio y
 * cron\u00f3metro. El bot\u00f3n "Volver al QR" solo existe en el perfil dev.
 */
public class BoardScreen {

  private static final Logger log = Logger.getLogger(BoardScreen.class.getName());

  private final BorderPane root;
  private final Clock clock;
  private final Label nameLabel;
  private final Label codeLabel;
  private final Label startLabel;
  private final Label elapsedLabel;
  private BoardScreenModel model;
  private Timeline ticker;
  private Runnable onBackToQr;

  public BoardScreen(boolean devProfile) {
    this(devProfile, Clock.systemDefaultZone());
  }

  BoardScreen(boolean devProfile, Clock clock) {
    this.clock = clock;

    Label title = new Label("Sesi\u00f3n activa");
    title.getStyleClass().add("board-title");
    title.setStyle("-fx-font-size: 28px; -fx-font-weight: 700;");

    nameLabel = new Label();
    nameLabel.getStyleClass().add("board-name");
    nameLabel.setStyle("-fx-font-size: 22px;");

    codeLabel = new Label();
    codeLabel.getStyleClass().add("board-code");

    startLabel = new Label();
    startLabel.getStyleClass().add("board-start");

    elapsedLabel = new Label();
    elapsedLabel.getStyleClass().add("board-elapsed");
    elapsedLabel.setStyle("-fx-font-size: 48px; -fx-font-weight: 700;");

    VBox center = new VBox(16, title, nameLabel, codeLabel, startLabel, elapsedLabel);
    center.setAlignment(Pos.CENTER);
    center.setPadding(new Insets(32));

    root = new BorderPane();
    root.getStyleClass().add("board-screen");
    root.setCenter(center);

    if (devProfile) {
      Button backButton = new Button("Volver al QR");
      backButton.getStyleClass().add("board-back");
      backButton.setOnAction(
          event -> {
            if (onBackToQr != null) {
              onBackToQr.run();
            }
          });
      HBox footer = new HBox(backButton);
      footer.setAlignment(Pos.CENTER_LEFT);
      footer.setPadding(new Insets(16));
      root.setBottom(footer);
    }
  }

  public BorderPane getRoot() {
    return root;
  }

  public void setOnBackToQr(Runnable onBackToQr) {
    this.onBackToQr = onBackToQr;
  }

  /**
   * Muestra el tablero y arranca el cron\u00f3metro desde la hora de {@code approved}. Debe
   * llamarse en el hilo de JavaFX, justo despu\u00e9s de poner la escena en el escenario.
   */
  public void show(String userName, String code, Instant approvedAt) {
    stop();
    model = new BoardScreenModel(userName, code, approvedAt, clock);
    render();
    startTicker();
    Instant visibleAt = clock.instant();
    long delayMillis = visibleAt.toEpochMilli() - approvedAt.toEpochMilli();
    log.info(
        "approved a las "
            + approvedAt
            + "; tablero visible a las "
            + visibleAt
            + " ("
            + delayMillis
            + " ms)");
  }

  /** Detiene el cron\u00f3metro. Se puede llamar m\u00e1s de una vez. */
  public void stop() {
    if (ticker != null) {
      ticker.stop();
      ticker = null;
    }
  }

  private void render() {
    nameLabel.setText(model.userName());
    codeLabel.setText("C\u00f3digo: " + model.maskedCode());
    startLabel.setText("Inicio: " + model.startTimeLabel());
    elapsedLabel.setText(model.elapsedLabel());
  }

  private void startTicker() {
    ticker =
        new Timeline(
            new KeyFrame(
                javafx.util.Duration.seconds(1),
                event -> elapsedLabel.setText(model.elapsedLabel())));
    ticker.setCycleCount(Timeline.INDEFINITE);
    ticker.play();
  }
}
