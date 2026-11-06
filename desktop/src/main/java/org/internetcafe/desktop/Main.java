package org.internetcafe.desktop;

import java.util.function.Consumer;
import javafx.animation.KeyFrame;
import javafx.animation.PauseTransition;
import javafx.animation.Timeline;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.scene.Scene;
import javafx.scene.input.KeyCombination;
import javafx.stage.Stage;
import javafx.util.Duration;
import org.internetcafe.desktop.qr.ConnectionMonitor;
import org.internetcafe.desktop.screens.BoardScreen;
import org.internetcafe.desktop.screens.ConnectionStatus;
import org.internetcafe.desktop.screens.DashboardScreen;
import org.internetcafe.desktop.screens.EnrollScreen;
import org.internetcafe.desktop.screens.LoginScreen;
import org.internetcafe.desktop.screens.MachineMode;
import org.internetcafe.desktop.screens.OfflineScreen;
import org.internetcafe.desktop.screens.PassiveCard;
import org.internetcafe.desktop.screens.QrScreen;
import org.internetcafe.desktop.screens.QrScreenModel;
import org.internetcafe.desktop.services.ApiClient;

public class Main extends Application {

  private TrayManager trayManager;
  private PassiveModeController passiveMode;
  private AppModeManager modeManager;
  private Timeline kioskFailOpenTicker;

  @Override
  public void start(Stage stage) {
    LoginScreen loginScreen = new LoginScreen();
    EnrollScreen enrollScreen = new EnrollScreen();
    QrScreenModel qrModel = new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 45);
    QrScreen qrScreen = new QrScreen(qrModel);
    DashboardScreen dashboardScreen = new DashboardScreen();
    BoardScreen boardScreen = new BoardScreen("dev".equals(System.getProperty("app.profile")));
    OfflineScreen offlineScreen = new OfflineScreen();
    ApiClient apiClient = new ApiClient();
    String machineCode = System.getProperty("machine.code", qrModel.machineCode());
    Scene scene = new Scene(loginScreen.getRoot(), 1280, 800);
    scene.getStylesheets().add(getClass().getResource("/styles.css").toExternalForm());

    stage.setTitle("Internet Cafe Desktop");
    stage.setScene(scene);
    stage.setMinWidth(900);
    stage.setMinHeight(700);
    KioskController kioskController =
        new KioskController(
            locked -> applyKioskWindow(stage, locked),
            failOpen -> {
              offlineScreen.setFailOpen(failOpen);
              if (failOpen && stage.getScene().getRoot() != offlineScreen.getRoot()) {
                qrScreen.stopRotation();
                stage.setScene(new Scene(offlineScreen.getRoot(), 1280, 800));
              }
            },
            System::nanoTime);

    Consumer<ConnectionMonitor.Status> onConnectionStatus =
        status -> {
          if (passiveMode != null && passiveMode.isPassive()) {
            return;
          }
          kioskController.onConnectionStatus(status);
          offlineScreen.show(status);
          boolean offlineVisible = stage.getScene().getRoot() == offlineScreen.getRoot();
          if (status.phase() == ConnectionMonitor.Phase.RESTORED) {
            if (offlineVisible) {
              PauseTransition pause = new PauseTransition(Duration.seconds(1.5));
              pause.setOnFinished(
                  event -> {
                    if (stage.getScene().getRoot() == offlineScreen.getRoot()) {
                      qrScreen.startRotation(apiClient, machineCode);
                      stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
                    }
                  });
              pause.play();
            }
          } else if (!offlineVisible) {
            qrScreen.stopRotation();
            stage.setScene(new Scene(offlineScreen.getRoot(), 1280, 800));
          }
        };
    ConnectionMonitor connectionMonitor =
        new ConnectionMonitor(
            apiClient::getHealth,
            status -> Platform.runLater(() -> onConnectionStatus.accept(status)));
    stage.setOnCloseRequest(
        event -> {
          if (kioskController.isLocked()) {
            event.consume();
          }
        });
    stage
        .iconifiedProperty()
        .addListener(
            (observable, wasIconified, iconified) -> {
              if (iconified && kioskController.isLocked()) {
                Platform.runLater(
                    () -> {
                      if (kioskController.isLocked() && stage.isShowing()) {
                        stage.setIconified(false);
                        stage.setFullScreen(true);
                        stage.toFront();
                      }
                    });
              }
            });
    stage.show();
    kioskFailOpenTicker =
        new Timeline(new KeyFrame(Duration.seconds(1), event -> kioskController.tick()));
    kioskFailOpenTicker.setCycleCount(Timeline.INDEFINITE);
    kioskFailOpenTicker.play();

    loginScreen.setOnLoginSuccess(
        () -> {
          stage.setScene(new Scene(dashboardScreen.getRoot(), 1280, 800));
          dashboardScreen.setStatus("Sesión iniciada");
        });

    loginScreen.setOnEnroll(
        () -> {
          stage.setScene(new Scene(enrollScreen.getRoot(), 1280, 800));
        });

    enrollScreen.setOnBack(
        () -> {
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });

    enrollScreen.setOnEnrollSuccess(
        () -> {
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
        });

    qrScreen.setOnBack(
        () -> {
          connectionMonitor.stop();
          qrScreen.stopRotation();
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });

    qrScreen.setOnConnectionLost(connectionMonitor::reportFailure);

    PassiveCard passiveCard = new PassiveCard();
    String passiveMachine = machineCode + " \u00b7 " + qrModel.labName();
    String passiveStatus = "QR detenido (omitido)";
    trayManager =
        new TrayManager(
            "Internet Caf\u00e9 - modo pasivo",
            () -> Platform.runLater(() -> passiveCard.show(passiveMachine, passiveStatus)),
            () -> Platform.runLater(() -> modeManager.applyMode(MachineMode.KIOSK)));
    passiveMode =
        new PassiveModeController(
            () -> {
              connectionMonitor.stop();
              qrScreen.stopRotation();
            },
            () -> qrScreen.startRotation(apiClient, machineCode),
            () -> {
              Platform.setImplicitExit(false);
              passiveCard.show(passiveMachine, passiveStatus);
              if (trayManager.install()) {
                stage.hide();
              } else {
                stage.setIconified(true);
              }
            },
            () -> {
              trayManager.remove();
              stage.setIconified(false);
              if (stage.getScene().getRoot() != qrScreen.getRoot()) {
                stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
              }
              stage.show();
              stage.toFront();
              passiveCard.hide();
              Platform.setImplicitExit(true);
            });
    modeManager =
        new AppModeManager(
            MachineMode.KIOSK,
            mode ->
                Platform.runLater(
                    () -> {
                      kioskController.setMode(mode);
                      passiveMode.applyMode(mode);
                    }));
    passiveCard.setOnRegister(() -> modeManager.applyMode(MachineMode.KIOSK));
    qrScreen.setOnSkip(() -> modeManager.applyMode(MachineMode.PASSIVE));

    offlineScreen.setOnRetry(connectionMonitor::retryNow);
    offlineScreen.setOnHome(
        () -> {
          connectionMonitor.stop();
          qrScreen.stopRotation();
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });

    boardScreen.setOnBackToQr(
        () -> {
          boardScreen.stop();
          kioskController.setSessionActive(false);
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
        });

    qrScreen.setOnApproved(
        (response, approvedAt) -> {
          connectionMonitor.stop();
          kioskController.setSessionActive(true);
          stage.setScene(new Scene(boardScreen.getRoot(), 1280, 800));
          boardScreen.show(response.displayName(), response.maskedStudentCode(), approvedAt);
        });

    dashboardScreen.setOnLogout(
        () -> {
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });
  }

  @Override
  public void stop() {
    if (kioskFailOpenTicker != null) {
      kioskFailOpenTicker.stop();
    }
    if (trayManager != null) {
      trayManager.remove();
    }
  }

  private static void applyKioskWindow(Stage stage, boolean locked) {
    stage.setAlwaysOnTop(locked);
    stage.setResizable(!locked);
    if (locked) {
      stage.setFullScreenExitHint("");
      stage.setFullScreenExitKeyCombination(KeyCombination.NO_MATCH);
    }
    stage.setFullScreen(locked);
  }

  public static void main(String[] args) {
    launch(args);
  }
}
