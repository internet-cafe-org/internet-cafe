package org.internetcafe.desktop.screens;

import com.google.zxing.common.BitMatrix;
import java.io.IOException;
import java.time.Instant;
import javafx.animation.KeyFrame;
import javafx.animation.Timeline;
import javafx.application.Platform;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.ProgressBar;
import javafx.scene.image.ImageView;
import javafx.scene.image.PixelWriter;
import javafx.scene.image.WritableImage;
import javafx.scene.layout.BorderPane;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Priority;
import javafx.scene.layout.Region;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.scene.paint.Color;
import javafx.util.Duration;
import org.internetcafe.desktop.contract.ChallengeWaitResponse;
import org.internetcafe.desktop.qr.ChallengeWaitService;
import org.internetcafe.desktop.qr.QrCountdown;
import org.internetcafe.desktop.qr.QrGenerator;
import org.internetcafe.desktop.qr.QrRotationService;
import org.internetcafe.desktop.services.ApiClient;
import org.internetcafe.desktop.services.ConnectivityErrors;

/** Pantalla D-02: QR, código del equipo, sala, cuenta regresiva y estado de conexión. */
public class QrScreen {

  private static final int QR_SIZE_PX = 280;
  private static final String[] CONNECTION_STYLE_CLASSES = {"online", "connecting", "offline"};

  /** A request to the API that may fail with a network error. */
  @FunctionalInterface
  private interface NetworkCall<T> {
    T run() throws IOException, InterruptedException;
  }

  private final BorderPane root;
  private final QrScreenModel model;
  private final Label connectionLabel;
  private final ImageView qrView;
  private final Label countdownLabel;
  private final ProgressBar countdownBar;
  private final Label machineCodeLabel;
  private final Label labLabel;
  private final Label readyBadge;
  private final Button skipButton;
  private Runnable onSkip;
  private volatile Runnable onConnectionLost;
  private volatile QrRotationService rotationService;
  private ChallengeWaitService waitService;
  private ChallengeWaitService.ApprovedListener onApproved;
  private Timeline countdownTimeline;
  private QrCountdown countdown;
  private int totalSeconds = 45;

  public QrScreen() {
    this(new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 45));
  }

  public QrScreen(QrScreenModel model) {
    this.model = model;
    this.totalSeconds = Math.max(1, model.remainingSeconds());

    // ── Header ──────────────────────────────────────────────────────────────
    Label brand = new Label("Acceso universitario");
    brand.getStyleClass().add("qr-brand");

    Label brandSub = new Label("Gestión de acceso");
    brandSub.getStyleClass().add("qr-brand-sub");

    VBox brandBox = new VBox(2, brand, brandSub);

    Label title = new Label("Control de acceso");
    title.getStyleClass().add("qr-title");

    connectionLabel = new Label();
    connectionLabel.getStyleClass().add("qr-connection");

    Region spacer = new Region();
    HBox.setHgrow(spacer, Priority.ALWAYS);

    HBox header = new HBox(16, brandBox, spacer, title, connectionLabel);
    header.getStyleClass().add("qr-header");
    header.setAlignment(Pos.CENTER_LEFT);

    // ── QR frame (left panel) ────────────────────────────────────────────────
    readyBadge = new Label("Listo para escanear");
    readyBadge.getStyleClass().add("qr-ready-badge");

    qrView = new ImageView();
    qrView.setFitWidth(QR_SIZE_PX);
    qrView.setFitHeight(QR_SIZE_PX);
    qrView.setPreserveRatio(true);
    qrView.setSmooth(false);

    StackPane qrFrame = new StackPane(qrView);
    qrFrame.getStyleClass().add("qr-frame");
    qrFrame.setMaxSize(Region.USE_PREF_SIZE, Region.USE_PREF_SIZE);

    countdownBar = new ProgressBar(1.0);
    countdownBar.getStyleClass().add("qr-countdown-bar");
    countdownBar.setMaxWidth(Double.MAX_VALUE);

    countdownLabel = new Label();
    countdownLabel.getStyleClass().add("qr-countdown");

    HBox countdownRow = new HBox(10, countdownLabel);
    countdownRow.setAlignment(Pos.CENTER_LEFT);

    machineCodeLabel = new Label();
    machineCodeLabel.getStyleClass().add("qr-machine-code");

    labLabel = new Label();
    labLabel.getStyleClass().add("qr-lab");

    Label machineRow = new Label();
    machineRow.getStyleClass().add("qr-machine-row");

    skipButton = new Button("Omitir  →");
    skipButton.getStyleClass().add("qr-skip");
    skipButton.setOnAction(
        event -> {
          if (onSkip != null) {
            onSkip.run();
          }
        });

    Label skipHint =
        new Label(
            "Omitir minimiza a la bandeja y pausa la generación de QR.\nPara reanudar, elige «Registrar acceso» en la bandeja.");
    skipHint.getStyleClass().add("qr-skip-hint");
    skipHint.setWrapText(true);
    skipHint.visibleProperty().bind(skipButton.visibleProperty());
    skipHint.managedProperty().bind(skipButton.managedProperty());

    // ── Layout según modo (los nodos NO se comparten entre layouts) ───────
    VBox center;
    if (model.machineMode() == MachineMode.KIOSK) {
      // Modo kiosco: pantalla centrada completa
      Label kioskModeLabel = new Label("MODO KIOSCO · ACCESO PRINCIPAL");
      kioskModeLabel.getStyleClass().add("qr-kiosk-mode-label");

      Label kioskTitle = new Label("Sin sesión activa");
      kioskTitle.getStyleClass().add("qr-kiosk-title");

      Label kioskSub = new Label("Registra tu acceso para utilizar el equipo.");
      kioskSub.getStyleClass().add("qr-kiosk-sub");

      Label kioskConfirm = new Label("□  Espera la confirmación en tu dispositivo.");
      kioskConfirm.getStyleClass().add("qr-kiosk-confirm");

      VBox kioskPanel =
          new VBox(
              10,
              kioskModeLabel,
              kioskTitle,
              kioskSub,
              readyBadge,
              qrFrame,
              machineCodeLabel,
              labLabel,
              countdownBar,
              countdownRow,
              kioskConfirm);
      kioskPanel.setAlignment(Pos.TOP_CENTER);
      kioskPanel.getStyleClass().add("qr-kiosk-panel");
      center = new VBox(0, kioskPanel);
    } else {
      // Modo pasivo: 2 columnas (QR izq + instrucciones der)
      VBox leftPanel =
          new VBox(10, readyBadge, qrFrame, countdownBar, countdownRow, machineCodeLabel, labLabel);
      leftPanel.setAlignment(Pos.TOP_CENTER);
      leftPanel.getStyleClass().add("qr-left-panel");

      Label credLabel = new Label("CREDENCIAL DIGITAL");
      credLabel.getStyleClass().add("qr-cred-label");

      Label instrTitle = new Label("Registra tu acceso");
      instrTitle.getStyleClass().add("qr-instr-title");

      Label instrDesc =
          new Label("Escanea el QR para abrir la aplicación web y registrar tu acceso.");
      instrDesc.getStyleClass().add("qr-instr-desc");
      instrDesc.setWrapText(true);

      VBox step1 = makeStep("□", "Escanea este código QR", "Usa la cámara de tu dispositivo.");
      VBox step2 = makeStep("⊡", "Abre la aplicación web", "Continúa desde el enlace del código.");
      VBox step3 =
          makeStep("◎", "Registra tu acceso", "Sigue las indicaciones y espera la confirmación.");

      VBox rightPanel = new VBox(16, credLabel, instrTitle, instrDesc, step1, step2, step3);
      rightPanel.getStyleClass().add("qr-right-panel");
      rightPanel.setAlignment(Pos.TOP_LEFT);
      HBox.setHgrow(rightPanel, Priority.ALWAYS);

      HBox passiveCard = new HBox(32, leftPanel, rightPanel);
      passiveCard.getStyleClass().add("qr-card");
      passiveCard.setAlignment(Pos.TOP_LEFT);

      Region footerSpacer = new Region();
      HBox.setHgrow(footerSpacer, Priority.ALWAYS);
      HBox omitirRow = new HBox(skipHint, footerSpacer, skipButton);
      omitirRow.setAlignment(Pos.CENTER_LEFT);
      omitirRow.getStyleClass().add("qr-omitir-row");
      omitirRow.visibleProperty().bind(skipButton.visibleProperty());
      omitirRow.managedProperty().bind(skipButton.managedProperty());

      center = new VBox(0, passiveCard, omitirRow);
    }

    center.setAlignment(Pos.TOP_CENTER);
    center.getStyleClass().add("qr-body");

    // ── Legal footer ──────────────────────────────────────────────────────
    Label legalLeft = new Label("El acceso es personal e intransferible");
    legalLeft.getStyleClass().add("qr-legal");

    Label legalCenter = new Label("El QR es de un solo uso y se renueva automáticamente.");
    legalCenter.getStyleClass().add("qr-legal");

    Label legalRight =
        new Label(model.machineCode() + " · " + model.labName() + " · Acceso principal");
    legalRight.getStyleClass().add("qr-legal");

    Region legalSpacer1 = new Region();
    HBox.setHgrow(legalSpacer1, Priority.ALWAYS);

    Region legalSpacer2 = new Region();
    HBox.setHgrow(legalSpacer2, Priority.ALWAYS);

    HBox legalFooter = new HBox(legalLeft, legalSpacer1, legalCenter, legalSpacer2, legalRight);
    legalFooter.getStyleClass().add("qr-legal-footer");
    legalFooter.setAlignment(Pos.CENTER);

    // ── Root ──────────────────────────────────────────────────────────────
    root = new BorderPane();
    root.getStyleClass().add("qr-screen");
    root.setTop(header);
    root.setCenter(center);
    root.setBottom(legalFooter);
    BorderPane.setMargin(header, new Insets(0));
    render();
  }

  private static VBox makeStep(String icon, String title, String desc) {
    Label iconLabel = new Label(icon);
    iconLabel.getStyleClass().add("qr-step-icon");

    Label titleLabel = new Label(title);
    titleLabel.getStyleClass().add("qr-step-title");

    Label descLabel = new Label(desc);
    descLabel.getStyleClass().add("qr-step-desc");

    VBox textBox = new VBox(2, titleLabel, descLabel);
    HBox row = new HBox(10, iconLabel, textBox);
    row.setAlignment(Pos.CENTER_LEFT);
    VBox box = new VBox(row);
    box.getStyleClass().add("qr-step");
    return box;
  }

  public BorderPane getRoot() {
    return root;
  }

  public QrScreenModel getModel() {
    return model;
  }

  /** Called on the JavaFX thread once the backend reports that the QR was claimed. */
  public void setOnApproved(ChallengeWaitService.ApprovedListener onApproved) {
    this.onApproved = onApproved;
  }

  public void setOnSkip(Runnable onSkip) {
    this.onSkip = onSkip;
  }

  /**
   * Called (from a background thread) when a request to the API fails because the network or the
   * API is down. The caller decides what to show.
   */
  public void setOnConnectionLost(Runnable onConnectionLost) {
    this.onConnectionLost = onConnectionLost;
  }

  /** Starts requesting challenges from the backend and keeps the QR and countdown up to date. */
  public void startRotation(ApiClient apiClient, String machineCode) {
    stopRotation();
    rotationService =
        new QrRotationService(
            () -> guarded(() -> apiClient.createChallenge(machineCode)), this::onChallengeReady);
    rotationService.start();
    waitService =
        new ChallengeWaitService(
            () -> guarded(() -> apiClient.waitForChallenge(machineCode)),
            this::stopRotationService,
            this::handleApproved);
    waitService.start();
  }

  /** Stops the rotation thread and the countdown ticks. Safe to call more than once. */
  public void stopRotation() {
    if (countdownTimeline != null) {
      countdownTimeline.stop();
      countdownTimeline = null;
    }
    countdown = null;
    if (waitService != null) {
      waitService.stop();
      waitService = null;
    }
    if (rotationService != null) {
      rotationService.stop();
      rotationService = null;
    }
  }

  /** Stops only the QR rotation. Safe to call from any thread. */
  private void stopRotationService() {
    QrRotationService current = rotationService;
    if (current != null) {
      current.stop();
    }
  }

  /** Runs a request and reports connection failures while the rotation is active. */
  private <T> T guarded(NetworkCall<T> call) throws IOException, InterruptedException {
    try {
      return call.run();
    } catch (IOException e) {
      Runnable callback = onConnectionLost;
      if (callback != null
          && rotationService != null
          && ConnectivityErrors.isConnectionFailure(e)) {
        callback.run();
      }
      throw e;
    }
  }

  private void handleApproved(ChallengeWaitResponse response, Instant approvedAt) {
    Platform.runLater(
        () -> {
          stopRotation();
          if (onApproved != null) {
            onApproved.onApproved(response, approvedAt);
          }
        });
  }

  private void onChallengeReady(BitMatrix qr, QrCountdown nextCountdown) {
    Runnable update =
        () -> {
          if (rotationService == null) {
            return;
          }
          qrView.setImage(toImage(qr));
          countdown = nextCountdown;
          // totalSeconds se mantiene del último challenge recibido (rotate_after_s)
          updateCountdownLabel();
          startCountdownTicks();
        };
    if (Platform.isFxApplicationThread()) {
      update.run();
    } else {
      Platform.runLater(update);
    }
  }

  private void startCountdownTicks() {
    if (countdownTimeline != null) {
      countdownTimeline.stop();
    }
    countdownTimeline =
        new Timeline(new KeyFrame(Duration.seconds(1), event -> updateCountdownLabel()));
    countdownTimeline.setCycleCount(Timeline.INDEFINITE);
    countdownTimeline.play();
  }

  private void updateCountdownLabel() {
    if (countdown == null) {
      return;
    }
    int remaining = countdown.remainingSeconds();
    int total = Math.max(1, totalSeconds);
    countdownLabel.setText(
        "Se renueva en  " + String.format("%02d:%02d", remaining / 60, remaining % 60));
    countdownBar.setProgress((double) remaining / total);
  }

  public void render() {
    connectionLabel.setText(model.connectionLabel());
    connectionLabel.getStyleClass().removeAll(CONNECTION_STYLE_CLASSES);
    connectionLabel.getStyleClass().add(model.connectionStyleClass());
    countdownLabel.setText(
        model.remainingSeconds() <= 0
            ? "Actualizando código…"
            : String.format(
                "Se renueva en  %02d:%02d",
                model.remainingSeconds() / 60, model.remainingSeconds() % 60));
    countdownBar.setProgress(model.remainingSeconds() <= 0 ? 0 : 1.0);
    machineCodeLabel.setText("🖥  " + model.machineCode() + "  ·  " + model.labName());
    labLabel.setText("");
    skipButton.setVisible(model.skipVisible());
    skipButton.setManaged(model.skipVisible());
    readyBadge.setText("⇄  Listo para escanear");
    qrView.setImage(toImage(QrGenerator.generate(model.qrPayload(), QR_SIZE_PX)));
  }

  private static WritableImage toImage(BitMatrix matrix) {
    int width = matrix.getWidth();
    int height = matrix.getHeight();
    WritableImage image = new WritableImage(width, height);
    PixelWriter writer = image.getPixelWriter();
    Color dark = Color.web("#0f172a");
    Color light = Color.WHITE;
    for (int y = 0; y < height; y++) {
      for (int x = 0; x < width; x++) {
        writer.setColor(x, y, matrix.get(x, y) ? dark : light);
      }
    }
    return image;
  }
}
