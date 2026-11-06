package org.internetcafe.desktop.screens;

import java.util.Objects;
import javafx.application.Platform;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Hyperlink;
import javafx.scene.control.Label;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.scene.text.TextAlignment;
import org.internetcafe.desktop.qr.ConnectionMonitor;

/** Pantalla "Sin conexión" (DSK-09): conectando, reintentando, fallo prolongado y restablecida. */
public class OfflineScreen {

  private static final String[] TONE_CLASSES = {"tone-info", "tone-warning", "tone-success"};

  private final StackPane root;
  private final Label icon = new Label();
  private final Label title = new Label();
  private final Label subtitle = new Label();
  private final Label detail = new Label();
  private final Label bannerTitle = new Label();
  private final Label bannerText = new Label();
  private final VBox banner = new VBox(2, bannerTitle, bannerText);
  private final Button retryButton = new Button();
  private final Hyperlink homeLink = new Hyperlink("Volver al inicio");
  private Runnable onRetry;
  private Runnable onHome;
  private OfflineScreenModel model;
  private boolean failOpen;

  public OfflineScreen() {
    icon.getStyleClass().add("offline-icon");
    title.getStyleClass().add("offline-title");
    subtitle.getStyleClass().add("offline-subtitle");
    detail.getStyleClass().add("offline-detail");
    bannerTitle.getStyleClass().add("offline-banner-title");
    bannerText.getStyleClass().add("offline-banner-text");
    banner.getStyleClass().add("offline-banner");
    banner.setAlignment(Pos.CENTER_LEFT);

    for (Label label : new Label[] {title, subtitle, detail}) {
      label.setWrapText(true);
      label.setTextAlignment(TextAlignment.CENTER);
    }
    bannerTitle.setWrapText(true);
    bannerText.setWrapText(true);

    retryButton.getStyleClass().add("offline-retry");
    retryButton.setMaxWidth(Double.MAX_VALUE);
    retryButton.setOnAction(
        event -> {
          if (onRetry != null) {
            onRetry.run();
          }
        });

    homeLink.getStyleClass().add("offline-home");
    homeLink.setOnAction(
        event -> {
          if (onHome != null) {
            onHome.run();
          }
        });

    VBox card = new VBox(12, icon, title, subtitle, banner, detail, retryButton, homeLink);
    card.setAlignment(Pos.CENTER);
    card.setMaxWidth(480);
    card.getStyleClass().add("offline-card");

    root = new StackPane(card);
    root.getStyleClass().add("offline-screen");
    root.getStylesheets()
        .add(
            Objects.requireNonNull(OfflineScreen.class.getResource("/offline.css"))
                .toExternalForm());

    apply(
        OfflineScreenModel.from(
            new ConnectionMonitor.Status(ConnectionMonitor.Phase.CONNECTING, 0, 0L)));
  }

  public StackPane getRoot() {
    return root;
  }

  public void setOnRetry(Runnable onRetry) {
    this.onRetry = onRetry;
  }

  public void setOnHome(Runnable onHome) {
    this.onHome = onHome;
  }

  /** Shows the given connection status. Safe to call from any thread. */
  public void show(ConnectionMonitor.Status status) {
    OfflineScreenModel nextModel = OfflineScreenModel.from(status);
    if (Platform.isFxApplicationThread()) {
      model = nextModel;
      apply(model);
    } else {
      Platform.runLater(
          () -> {
            model = nextModel;
            apply(model);
          });
    }
  }

  /** Shows whether the kiosk was released after the API remained unavailable for three minutes. */
  public void setFailOpen(boolean failOpen) {
    Runnable update =
        () -> {
          this.failOpen = failOpen;
          apply(model);
        };
    if (Platform.isFxApplicationThread()) {
      update.run();
    } else {
      Platform.runLater(update);
    }
  }

  private void apply(OfflineScreenModel model) {
    if (model == null) {
      return;
    }
    icon.setText(model.icon());
    title.setText(model.title());
    subtitle.setText(model.subtitle());
    detail.setText(model.detail());
    setShown(detail, !model.detail().isBlank());

    String toneClass = model.tone().styleClass();
    for (Node node : new Node[] {icon, banner}) {
      node.getStyleClass().removeAll(TONE_CLASSES);
      node.getStyleClass().add(toneClass);
    }
    bannerTitle.setText(model.bannerTitle());
    bannerText.setText(model.bannerText());
    setShown(banner, !model.bannerTitle().isBlank());
    setShown(bannerText, !model.bannerText().isBlank());
    if (failOpen) {
      title.setText("Equipo liberado");
      subtitle.setText("La API lleva 3 minutos sin responder. Puede usar el equipo.");
      bannerTitle.setText("Modo de emergencia");
      bannerText.setText("El equipo volverá al modo kiosco cuando se recupere la conexión.");
      setShown(banner, true);
      setShown(bannerText, true);
    }

    retryButton.setText(model.retryLabel());
    retryButton.setDisable(!model.retryEnabled());
    setShown(retryButton, model.retryVisible());
    setShown(homeLink, model.homeVisible());
  }

  private static void setShown(Node node, boolean shown) {
    node.setVisible(shown);
    node.setManaged(shown);
  }
}
