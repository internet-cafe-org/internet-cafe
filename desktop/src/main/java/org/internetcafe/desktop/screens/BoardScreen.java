package org.internetcafe.desktop.screens;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.logging.Logger;
import javafx.animation.KeyFrame;
import javafx.animation.Timeline;
import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.VBox;
import org.internetcafe.desktop.contract.RecentSession;

/**
 * Pantalla D-03 (tablero de sesión activa): nombre, código enmascarado, hora de inicio,
 * cronómetro, últimos 5 accesos y botón "Cerrar sesión" (RF-EQU-09).
 *
 * <p>"Volver al QR" solo se muestra en el perfil dev (DSK-06 / DSK-08).
 */
public class BoardScreen {

  private static final Logger log = Logger.getLogger(BoardScreen.class.getName());
  private static final DateTimeFormatter TIME_FMT =
      DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.systemDefault());
  private static final DateTimeFormatter DATETIME_FMT =
      DateTimeFormatter.ofPattern("dd/MM HH:mm").withZone(ZoneId.systemDefault());

  private final BorderPane root;
  private final Clock clock;
  private final Label nameLabel;
  private final Label codeLabel;
  private final Label startLabel;
  private final Label elapsedLabel;
  private final Button logoutButton;
  private final VBox recentSessionsBox;
  private final Label recentSessionsTitle;
  private BoardScreenModel model;
  private Timeline ticker;
  private Runnable onBackToQr;
  private Runnable onLogout;

  public BoardScreen(boolean devProfile) {
    this(devProfile, Clock.systemDefaultZone());
  }

  BoardScreen(boolean devProfile, Clock clock) {
    this.clock = clock;

    Label title = new Label("Sesión activa");
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

    logoutButton = new Button("Cerrar sesión");
    logoutButton.getStyleClass().add("board-logout");
    logoutButton.setOnAction(
        event -> {
          if (onLogout != null) {
            onLogout.run();
          }
        });

    // ── Últimos 5 accesos (RF-EQU-09) ──────────────────────────────────────
    recentSessionsTitle = new Label("Últimos accesos");
    recentSessionsTitle.setStyle("-fx-font-size: 14px; -fx-font-weight: 700; -fx-opacity: 0.7;");

    recentSessionsBox = new VBox(4);
    recentSessionsBox.setAlignment(Pos.CENTER);
    recentSessionsBox.getStyleClass().add("board-recent-sessions");
    Label loadingLabel = new Label("Cargando accesos anteriores…");
    loadingLabel.setStyle("-fx-opacity: 0.5; -fx-font-size: 13px;");
    recentSessionsBox.getChildren().add(loadingLabel);

    VBox sessionHistory = new VBox(6, recentSessionsTitle, recentSessionsBox);
    sessionHistory.setAlignment(Pos.CENTER);
    sessionHistory.setPadding(new Insets(8, 0, 0, 0));
    // ───────────────────────────────────────────────────────────────────────

    VBox center =
        new VBox(16, title, nameLabel, codeLabel, startLabel, elapsedLabel, logoutButton,
            sessionHistory);
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

  public void setOnLogout(Runnable onLogout) {
    this.onLogout = onLogout;
  }

  /** Habilita o deshabilita "Cerrar sesión" (deshabilitado mientras la petición está en vuelo). */
  public void setLogoutEnabled(boolean enabled) {
    logoutButton.setDisable(!enabled);
  }

  /**
   * Muestra el tablero y arranca el cronómetro desde {@code approvedAt}.
   * Debe llamarse en el hilo de JavaFX, justo después de poner la escena en el escenario.
   */
  public void show(String userName, String code, Instant approvedAt) {
    stop();
    model = new BoardScreenModel(userName, code, approvedAt, clock);
    setLogoutEnabled(true);
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

  /**
   * Muestra los últimos accesos en la sección inferior del tablero (RF-EQU-09).
   * Debe llamarse en el hilo de JavaFX.
   *
   * @param sessions lista de sesiones recientes (puede estar vacía)
   */
  public void showRecentSessions(List<RecentSession> sessions) {
    recentSessionsBox.getChildren().clear();
    if (sessions == null || sessions.isEmpty()) {
      Label empty = new Label("Sin accesos anteriores registrados");
      empty.setStyle("-fx-opacity: 0.45; -fx-font-size: 13px;");
      recentSessionsBox.getChildren().add(empty);
      return;
    }
    for (RecentSession s : sessions) {
      String text = formatSession(s);
      Label row = new Label(text);
      row.setStyle("-fx-font-size: 13px;");
      row.getStyleClass().add("board-recent-row");
      recentSessionsBox.getChildren().add(row);
    }
  }

  /** Detiene el cronómetro. Se puede llamar más de una vez. */
  public void stop() {
    if (ticker != null) {
      ticker.stop();
      ticker = null;
    }
  }

  private void render() {
    nameLabel.setText(model.userName());
    codeLabel.setText("Código: " + model.maskedCode());
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

  private String formatSession(RecentSession s) {
    try {
      Instant start = Instant.parse(s.startedAt());
      String startStr = DATETIME_FMT.format(start);
      if (s.endedAt() != null && !s.endedAt().isBlank()) {
        Instant end = Instant.parse(s.endedAt());
        long minutes =
            java.time.Duration.between(start, end).abs().toMinutes();
        return startStr + " · " + minutes + " min";
      }
      return startStr;
    } catch (Exception e) {
      return s.startedAt();
    }
  }
}
