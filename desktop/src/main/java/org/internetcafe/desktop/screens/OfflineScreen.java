package org.internetcafe.desktop.screens;

import java.util.Objects;
import javafx.application.Platform;
import javafx.geometry.Pos;
import javafx.scene.Node;
import javafx.scene.control.Button;
import javafx.scene.control.Hyperlink;
import javafx.scene.control.Label;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.scene.text.TextAlignment;
import org.internetcafe.desktop.qr.ConnectionMonitor;

/**
 * Pantalla D-04 "Sin conexión": conectando, reintentando, fallo prolongado, restablecida y modo
 * fail-open (kiosco liberado).
 */
public class OfflineScreen {

  private static final String[] TONE_CLASSES = {"tone-info", "tone-warning", "tone-success"};

  private final StackPane root;

  // Compact single-column card (normal offline states)
  private final Label icon = new Label();
  private final Label title = new Label();
  private final Label subtitle = new Label();
  private final Label detail = new Label();
  private final Label bannerTitle = new Label();
  private final Label bannerText = new Label();
  private final VBox banner = new VBox(2, bannerTitle, bannerText);
  private final Button retryButton = new Button();
  private final Hyperlink homeLink = new Hyperlink("Volver al inicio");
  private final VBox compactCard;

  // Fail-open two-column layout
  private final VBox failOpenCard;
  private final Label failOpenBannerTitle = new Label("Modo fail-open activo");
  private final Label failOpenBannerText =
      new Label(
          "La API no ha respondido durante 3 minutos. Se ha liberado el equipo según la configuración.");
  private final Label failOpenBadge = new Label("Equipo liberado");
  private final Button retryNowButton = new Button("Reintentar ahora  ⟳");
  private final Button contactButton = new Button("Contactar soporte  ↗");

  private Runnable onRetry;
  private Runnable onHome;
  private OfflineScreenModel model;
  private boolean failOpen;

  public OfflineScreen() {
    // ── Compact card (connecting / retrying / restored) ───────────────────
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
          if (onRetry != null) onRetry.run();
        });

    homeLink.getStyleClass().add("offline-home");
    homeLink.setOnAction(
        event -> {
          if (onHome != null) onHome.run();
        });

    compactCard = new VBox(12, icon, title, subtitle, banner, detail, retryButton, homeLink);
    compactCard.setAlignment(Pos.CENTER);
    compactCard.setMaxWidth(480);
    compactCard.getStyleClass().add("offline-card");

    // ── Fail-open two-column layout ───────────────────────────────────────
    // Warning banner (top)
    failOpenBannerTitle.getStyleClass().add("fo-banner-title");
    failOpenBannerText.getStyleClass().add("fo-banner-text");
    failOpenBannerText.setWrapText(true);
    failOpenBadge.getStyleClass().add("fo-badge");

    Region bannerSpacer = new Region();
    HBox.setHgrow(bannerSpacer, Priority.ALWAYS);
    HBox foBannerRow = new HBox(10, failOpenBannerTitle, bannerSpacer, failOpenBadge);
    foBannerRow.setAlignment(Pos.CENTER_LEFT);
    VBox foBanner = new VBox(4, foBannerRow, failOpenBannerText);
    foBanner.getStyleClass().add("fo-banner");

    // Left: QR placeholder
    Label qrPlaceholderIcon = new Label("⊡");
    qrPlaceholderIcon.getStyleClass().add("fo-qr-icon");
    Label qrPlaceholderLabel = new Label("QR no disponible");
    qrPlaceholderLabel.getStyleClass().add("fo-qr-label");
    Label qrReturnHint = new Label("Se mostrará de nuevo cuando vuelva el servicio.");
    qrReturnHint.getStyleClass().add("fo-qr-hint");

    VBox foLeft = new VBox(12, qrPlaceholderIcon, qrPlaceholderLabel, qrReturnHint);
    foLeft.setAlignment(Pos.CENTER);
    foLeft.getStyleClass().add("fo-left");
    HBox.setHgrow(foLeft, Priority.ALWAYS);

    // Right: message
    Label foRightTitle = new Label("Equipo liberado: puedes utilizarlo");
    foRightTitle.getStyleClass().add("fo-right-title");
    foRightTitle.setWrapText(true);

    Label foRightDesc =
        new Label(
            "La terminal no puede comunicarse con la API de acceso. El equipo ya está disponible para su uso.");
    foRightDesc.getStyleClass().add("fo-right-desc");
    foRightDesc.setWrapText(true);

    Label foCredWarningTitle = new Label("Credenciales sin verificar");
    foCredWarningTitle.getStyleClass().add("fo-cred-title");
    Label foCredWarningDesc =
        new Label(
            "El equipo está liberado, pero las credenciales no se están verificando. "
                + "Sigue el protocolo de contingencia de tu institución.");
    foCredWarningDesc.getStyleClass().add("fo-cred-desc");
    foCredWarningDesc.setWrapText(true);
    VBox foCredBox = new VBox(4, foCredWarningTitle, foCredWarningDesc);
    foCredBox.getStyleClass().add("fo-cred-box");

    VBox foRight = new VBox(14, foRightTitle, foRightDesc, foCredBox);
    foRight.setAlignment(Pos.TOP_LEFT);
    foRight.getStyleClass().add("fo-right");
    HBox.setHgrow(foRight, Priority.ALWAYS);

    HBox foCols = new HBox(0, foLeft, foRight);
    foCols.getStyleClass().add("fo-cols");

    // Footer buttons
    retryNowButton.getStyleClass().addAll("button", "fo-retry-btn");
    retryNowButton.setOnAction(
        event -> {
          if (onRetry != null) onRetry.run();
        });
    contactButton.getStyleClass().addAll("fo-contact-btn");
    contactButton.setOnAction(
        event -> {
          if (onHome != null) onHome.run();
        });

    Label foStatus = new Label("Sin servicio · Reconectando con espera creciente...");
    foStatus.getStyleClass().add("fo-status");
    HBox.setHgrow(foStatus, Priority.ALWAYS);

    Region foFooterSpacer = new Region();
    HBox foFooter = new HBox(12, foStatus, foFooterSpacer, contactButton, retryNowButton);
    foFooter.setAlignment(Pos.CENTER_LEFT);
    foFooter.getStyleClass().add("fo-footer");

    failOpenCard = new VBox(0, foBanner, foCols, foFooter);
    failOpenCard.getStyleClass().add("fo-card");
    failOpenCard.setMaxWidth(900);

    // ── Root ─────────────────────────────────────────────────────────────
    root = new StackPane(compactCard);
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
    if (failOpen) {
      // Switch to fail-open two-column layout
      root.getChildren().setAll(failOpenCard);
      return;
    }

    root.getChildren().setAll(compactCard);

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
