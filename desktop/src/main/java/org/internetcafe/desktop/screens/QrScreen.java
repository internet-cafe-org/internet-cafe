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

  private static final int QR_SIZE_PX = 320;
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
  private final Label machineCodeLabel;
  private final Label labLabel;
  private final Button skipButton;
  private Runnable onBack;
  private Runnable onSkip;
  private volatile Runnable onConnectionLost;
  private volatile QrRotationService rotationService;
  private ChallengeWaitService waitService;
  private ChallengeWaitService.ApprovedListener onApproved;
  private Timeline countdownTimeline;
  private QrCountdown countdown;

  public QrScreen() {
    this(new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 45));
  }

  public QrScreen(QrScreenModel model) {
    this.model = model;

    Label brand = new Label("Internet Café");
    brand.getStyleClass().add("qr-brand");

    connectionLabel = new Label();
    connectionLabel.getStyleClass().add("qr-connection");

    Region spacer = new Region();
    HBox.setHgrow(spacer, Priority.ALWAYS);

    HBox header = new HBox(12, brand, spacer, connectionLabel);
    header.getStyleClass().add("qr-header");
    header.setAlignment(Pos.CENTER_LEFT);

    qrView = new ImageView();
    qrView.setFitWidth(QR_SIZE_PX);
    qrView.setFitHeight(QR_SIZE_PX);
    qrView.setPreserveRatio(true);
    qrView.setSmooth(false);

    StackPane qrFrame = new StackPane(qrView);
    qrFrame.getStyleClass().add("qr-frame");
    qrFrame.setMaxSize(Region.USE_PREF_SIZE, Region.USE_PREF_SIZE);

    countdownLabel = new Label();
    countdownLabel.getStyleClass().add("qr-countdown");

    machineCodeLabel = new Label();
    machineCodeLabel.getStyleClass().add("qr-machine-code");

    labLabel = new Label();
    labLabel.getStyleClass().add("qr-lab");

    skipButton = new Button("Omitir");
    skipButton.getStyleClass().add("qr-skip");
    skipButton.setOnAction(
        event -> {
          if (onSkip != null) {
            onSkip.run();
          }
        });

    Button backButton = new Button("Volver");
    backButton.getStyleClass().add("qr-back");
    backButton.setOnAction(
        event -> {
          if (onBack != null) {
            onBack.run();
          }
        });

    Label skipHint = new Label("Minimiza a la bandeja y detiene los QR hasta registrar acceso");
    skipHint.getStyleClass().add("qr-skip-hint");
    skipHint.visibleProperty().bind(skipButton.visibleProperty());
    skipHint.managedProperty().bind(skipButton.managedProperty());

    VBox center =
        new VBox(16, qrFrame, countdownLabel, machineCodeLabel, labLabel, skipButton, skipHint);
    center.setAlignment(Pos.CENTER);
    center.getStyleClass().add("qr-body");

    HBox footer = new HBox(backButton);
    footer.setAlignment(Pos.CENTER_LEFT);
    footer.getStyleClass().add("qr-footer");

    root = new BorderPane();
    root.getStyleClass().add("qr-screen");
    root.setTop(header);
    root.setCenter(center);
    root.setBottom(footer);
    BorderPane.setMargin(header, new Insets(0));
    render();
  }

  public BorderPane getRoot() {
    return root;
  }

  public QrScreenModel getModel() {
    return model;
  }

  public void setOnBack(Runnable onBack) {
    this.onBack = onBack;
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
    countdownLabel.setText("Expira en " + countdown.remainingSeconds() + " s");
  }

  public void render() {
    connectionLabel.setText(model.connectionLabel());
    connectionLabel.getStyleClass().removeAll(CONNECTION_STYLE_CLASSES);
    connectionLabel.getStyleClass().add(model.connectionStyleClass());
    countdownLabel.setText(model.countdownLabel());
    machineCodeLabel.setText(model.machineCode());
    labLabel.setText(model.labName());
    skipButton.setVisible(model.skipVisible());
    skipButton.setManaged(model.skipVisible());
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
