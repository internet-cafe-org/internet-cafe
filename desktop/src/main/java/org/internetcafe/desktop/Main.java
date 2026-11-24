package org.internetcafe.desktop;

import java.io.IOException;
import java.security.GeneralSecurityException;
import java.util.Arrays;
import java.util.function.Consumer;
import java.util.logging.Logger;
import javafx.animation.KeyFrame;
import javafx.animation.PauseTransition;
import javafx.animation.Timeline;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.scene.Scene;
import javafx.scene.control.Alert;
import javafx.scene.input.KeyCombination;
import javafx.stage.Stage;
import javafx.util.Duration;
import org.internetcafe.desktop.contract.EnrollmentResponse;
import org.internetcafe.desktop.identity.EnrollmentStore;
import org.internetcafe.desktop.identity.MachineIdentity;
import org.internetcafe.desktop.identity.MachineIdentityPasswordStore;
import org.internetcafe.desktop.identity.MachineIdentityStore;
import org.internetcafe.desktop.identity.WindowsDpapiProtector;
import org.internetcafe.desktop.qr.ConnectionMonitor;
import org.internetcafe.desktop.qr.HeartbeatService;
import org.internetcafe.desktop.screens.BoardScreen;
import org.internetcafe.desktop.screens.ConnectionStatus;
import org.internetcafe.desktop.screens.EnrollScreen;
import org.internetcafe.desktop.screens.MachineMode;
import org.internetcafe.desktop.screens.OfflineScreen;
import org.internetcafe.desktop.screens.PassiveCard;
import org.internetcafe.desktop.screens.QrScreen;
import org.internetcafe.desktop.screens.QrScreenModel;
import org.internetcafe.desktop.services.ApiClient;
import org.internetcafe.desktop.services.ApiException;
import org.internetcafe.desktop.services.EnrollmentCommitException;
import org.internetcafe.desktop.services.EnrollmentService;
import org.internetcafe.desktop.signing.RequestSigner;

public class Main extends Application {

  private TrayManager trayManager;
  private PassiveModeController passiveMode;
  private AppModeManager modeManager;
  private static final Logger LOG = Logger.getLogger(Main.class.getName());
  private HeartbeatService heartbeatService;
  private Timeline kioskFailOpenTicker;

  @Override
  public void start(Stage stage) {
    stage.setTitle("Internet Cafe Desktop");
    stage.setMinWidth(900);
    stage.setMinHeight(700);
    if (getParameters().getRaw().contains("--enroll")) {
      startEnrollment(stage);
      return;
    }

    // ── Dev mode: saltar enrolamiento con valores de prueba ──────────────
    final boolean devMode = "dev".equals(System.getProperty("app.profile"));
    EnrolledMachine enrolledMachine;
    if (devMode) {
      // Permite cambiar el modo de prueba con -Ddev.mode=kiosk (por defecto: passive)
      String devModeStr = System.getProperty("dev.mode", "passive");
      MachineMode devMachineMode =
          "kiosk".equalsIgnoreCase(devModeStr) ? MachineMode.KIOSK : MachineMode.PASSIVE;
      enrolledMachine = new EnrolledMachine("AC-024", "Laboratorio 1", devMachineMode, null);
    } else {
      try {
        enrolledMachine = loadEnrolledMachine();
      } catch (IOException
          | GeneralSecurityException
          | IllegalArgumentException
          | IllegalStateException exception) {
        LOG.warning(
            "Machine identity could not be loaded: " + exception.getClass().getSimpleName());
        Alert alert = new Alert(Alert.AlertType.ERROR);
        alert.setTitle("Equipo no disponible");
        alert.setHeaderText("No se pudo cargar la identidad enrolada");
        alert.setContentText(
            "No se enviará peticiones del equipo. Verifica el enrolamiento o contacta a TI.");
        alert.showAndWait();
        Platform.exit();
        return;
      }
    }

    QrScreenModel qrModel =
        new QrScreenModel(
            enrolledMachine.code(),
            enrolledMachine.lab(),
            ConnectionStatus.ONLINE,
            45,
            enrolledMachine.mode());
    QrScreen qrScreen = new QrScreen(qrModel);
    BoardScreen boardScreen = new BoardScreen(devMode);
    OfflineScreen offlineScreen = new OfflineScreen();
    ApiClient apiClient =
        devMode ? new ApiClient() : new ApiClient(enrolledMachine.requestSigner());
    String machineCode = enrolledMachine.code();
    final boolean darkMode = WindowsDarkMode.isSystemDarkMode();
    stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
    KioskController kioskController =
        new KioskController(
            locked -> applyKioskWindow(stage, locked),
            failOpen -> {
              offlineScreen.setFailOpen(failOpen);
              if (failOpen && stage.getScene().getRoot() != offlineScreen.getRoot()) {
                qrScreen.stopRotation();
                stage.setScene(makeScene(offlineScreen.getRoot(), darkMode));
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
                      stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
                    }
                  });
              pause.play();
            }
          } else if (!offlineVisible) {
            qrScreen.stopRotation();
            stage.setScene(makeScene(offlineScreen.getRoot(), darkMode));
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
    // D-02: arranca la rotación del QR en cuanto la ventana es visible (RF-QR-01, RF-EQU-04).
    qrScreen.startRotation(apiClient, machineCode);
    kioskFailOpenTicker =
        new Timeline(new KeyFrame(Duration.seconds(1), event -> kioskController.tick()));
    kioskFailOpenTicker.setCycleCount(Timeline.INDEFINITE);
    kioskFailOpenTicker.play();

    // El QR es la pantalla de inicio: no hay pantalla anterior a la que volver.
    // En modo pasivo el usuario puede omitir via el botón "Omitir".

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
                stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
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
    modeManager.applyMode(enrolledMachine.mode());
    passiveCard.setOnRegister(() -> modeManager.applyMode(MachineMode.KIOSK));
    qrScreen.setOnSkip(() -> modeManager.applyMode(MachineMode.PASSIVE));

    offlineScreen.setOnRetry(connectionMonitor::retryNow);
    // "Inicio" desde la pantalla offline vuelve al QR (D-02), que es la pantalla raíz.
    offlineScreen.setOnHome(
        () -> {
          connectionMonitor.stop();
          qrScreen.stopRotation();
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
        });

    boardScreen.setOnBackToQr(
        () -> {
          boardScreen.stop();
          kioskController.setSessionActive(false);
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
        });

    Runnable backToQr =
        () -> {
          boardScreen.stop();
          heartbeatService.setSessionId(null);
          kioskController.setSessionActive(false);
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(makeScene(qrScreen.getRoot(), darkMode));
        };
    heartbeatService =
        new HeartbeatService(
            sessionId -> apiClient.sendHeartbeat(machineCode, sessionId),
            (sessionId, reason) -> Platform.runLater(backToQr));
    heartbeatService.start();
    Runtime.getRuntime()
        .addShutdownHook(
            new Thread(
                new SessionShutdownHook(
                    heartbeatService::hasActiveSession,
                    () -> apiClient.endCurrentSessionForShutdown(machineCode)),
                "session-shutdown"));
    boardScreen.setOnLogout(
        () -> {
          boardScreen.setLogoutEnabled(false);
          Thread closer =
              new Thread(
                  () -> {
                    try {
                      apiClient.endCurrentSession(machineCode);
                    } catch (Exception e) {
                      LOG.warning(
                          "No se pudo cerrar la sesion en el servidor: "
                              + e.getClass().getSimpleName());
                    }
                    Platform.runLater(backToQr);
                  },
                  "session-end");
          closer.setDaemon(true);
          closer.start();
        });
    qrScreen.setOnApproved(
        (response, approvedAt) -> {
          connectionMonitor.stop();
          kioskController.setSessionActive(true);
          heartbeatService.setSessionId(
              response.session() == null ? null : response.session().id());
          stage.setScene(makeScene(boardScreen.getRoot(), darkMode));
          boardScreen.show(response.displayName(), response.maskedStudentCode(), approvedAt);
          // Carga los últimos 5 accesos en segundo plano (RF-EQU-09).
          Thread.startVirtualThread(
              () -> {
                try {
                  var sessions = apiClient.getRecentSessions(machineCode, 5);
                  Platform.runLater(() -> boardScreen.showRecentSessions(sessions));
                } catch (Exception ex) {
                  LOG.warning("No se pudieron cargar los accesos recientes: " + ex.getMessage());
                  Platform.runLater(() -> boardScreen.showRecentSessions(java.util.List.of()));
                }
              });
        });
  }

  @Override
  public void stop() {
    if (heartbeatService != null) {
      heartbeatService.stop();
    }
    if (kioskFailOpenTicker != null) {
      kioskFailOpenTicker.stop();
    }
    if (trayManager != null) {
      trayManager.remove();
    }
  }

  private void startEnrollment(Stage stage) {
    EnrollScreen enrollScreen = new EnrollScreen();
    stage.setScene(makeScene(enrollScreen.getRoot(), WindowsDarkMode.isSystemDarkMode()));
    stage.show();
    enrollScreen.setOnClose(Platform::exit);

    try {
      if (!WindowsElevation.isAdministrator()) {
        enrollScreen.setAvailable(
            false, "Cierra la aplicación e iníciala con permisos de administrador para enrolar.");
        return;
      }

      WindowsDpapiProtector protector = new WindowsDpapiProtector();
      char[] password = MachineIdentityPasswordStore.underLocalAppData(protector).loadOrCreate();
      MachineIdentityStore identityStore;
      try {
        identityStore = MachineIdentityStore.underProgramData(password);
      } finally {
        Arrays.fill(password, '\0');
      }
      EnrollmentService enrollmentService =
          new EnrollmentService(
              new ApiClient(), identityStore, EnrollmentStore.underLocalAppData(protector));
      enrollScreen.setAvailable(true, "Ingresa el código de un solo uso entregado por TI.");
      enrollScreen.setOnEnroll(
          code -> {
            enrollScreen.setBusy();
            Thread.startVirtualThread(
                () -> {
                  try {
                    EnrollmentResponse response = enrollmentService.enroll(code);
                    Platform.runLater(() -> enrollScreen.showSuccess(response));
                  } catch (EnrollmentCommitException exception) {
                    Platform.runLater(
                        () ->
                            enrollScreen.showFinalFailure(
                                "El servidor aceptó el equipo, pero no se pudo verificar o "
                                    + "guardar el resultado. Contacta a TI antes de reintentar."));
                  } catch (ApiException exception) {
                    Platform.runLater(
                        () -> enrollScreen.showFailure(enrollmentErrorMessage(exception)));
                  } catch (IllegalArgumentException exception) {
                    Platform.runLater(
                        () ->
                            enrollScreen.showFailure(
                                "El código debe tener entre 8 y 64 caracteres."));
                  } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    Platform.runLater(
                        () ->
                            enrollScreen.showFailure(
                                "El enrolamiento se interrumpió. Vuelve a intentarlo."));
                  } catch (IOException | GeneralSecurityException exception) {
                    Platform.runLater(
                        () ->
                            enrollScreen.showFailure(
                                "No se recibió una confirmación segura. El servidor pudo haber "
                                    + "consumido el código; consulta a TI antes de reintentar."));
                  }
                });
          });
    } catch (IOException | GeneralSecurityException | IllegalStateException exception) {
      enrollScreen.setAvailable(false, "No se pudo preparar el almacenamiento seguro del equipo.");
    } catch (InterruptedException exception) {
      Thread.currentThread().interrupt();
      enrollScreen.setAvailable(false, "No se pudo comprobar el permiso de administrador.");
    }
  }

  private EnrolledMachine loadEnrolledMachine() throws IOException, GeneralSecurityException {
    WindowsDpapiProtector protector = new WindowsDpapiProtector();
    EnrollmentResponse enrollment = EnrollmentStore.underLocalAppData(protector).load();
    char[] password = MachineIdentityPasswordStore.underLocalAppData(protector).loadExisting();
    MachineIdentity identity;
    try {
      identity = MachineIdentityStore.underProgramData(password).loadExisting();
    } finally {
      Arrays.fill(password, '\0');
    }
    if (enrollment.keyid() == null || !identity.publicJwk().matchesThumbprint(enrollment.keyid())) {
      throw new GeneralSecurityException("Stored enrollment does not match the machine identity");
    }
    if (enrollment.code() == null || enrollment.code().isBlank()) {
      throw new IOException("Stored enrollment is missing the machine code");
    }
    if (enrollment.lab() == null || enrollment.lab().isBlank()) {
      throw new IOException("Stored enrollment is missing the room");
    }
    MachineMode mode;
    try {
      mode = MachineMode.valueOf(enrollment.mode().toUpperCase(java.util.Locale.ROOT));
    } catch (NullPointerException | IllegalArgumentException exception) {
      throw new IOException("Stored enrollment contains an invalid machine mode", exception);
    }
    return new EnrolledMachine(
        enrollment.code(),
        enrollment.lab(),
        mode,
        new RequestSigner(identity.privateKey(), identity.publicJwk()));
  }

  private record EnrolledMachine(
      String code, String lab, MachineMode mode, RequestSigner requestSigner) {}

  private static String enrollmentErrorMessage(ApiException exception) {
    return switch (exception.getStatusCode()) {
      case 401 -> "El código no es válido, ya se usó o venció.";
      case 409 -> "La clave de este equipo ya está registrada.";
      case 422 -> "El código o la clave del equipo no cumple el contrato de enrolamiento.";
      case 429 -> "Se alcanzó el límite de intentos. Espera antes de volver a intentarlo.";
      default ->
          "El servidor no pudo completar el enrolamiento (HTTP " + exception.getStatusCode() + ").";
    };
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

  /**
   * Crea una escena con los estilos base y, si el sistema está en modo oscuro, aplica también el
   * override oscuro.
   */
  private Scene makeScene(javafx.scene.Parent root, boolean darkMode) {
    Scene scene = new Scene(root, 1280, 800);
    scene.getStylesheets().add(getClass().getResource("/styles.css").toExternalForm());
    if (darkMode) {
      scene.getStylesheets().add(getClass().getResource("/styles-dark.css").toExternalForm());
    }
    return scene;
  }

  /**
   * Lee el argumento {@code --api-base-url=<url>} de la línea de comandos y, si está presente,
   * lo establece como propiedad del sistema {@code api.base.url} con la mayor prioridad, antes de
   * que {@link AppConfig#getApiBaseUrl()} sea invocado por primera vez. Esto permite que el script
   * de arranque {@code Register-Startup.ps1} sobreescriba la URL que quedó fija en el MSI al
   * momento del build, sin necesidad de recompilar la aplicación.
   *
   * <p>El formato aceptado es {@code --api-base-url=https://host} (sin barra final). Si el
   * argumento aparece más de una vez, se usa la última ocurrencia.
   *
   * @param args argumentos tal como los recibe {@link #main(String[])}.
   */
  static void applyApiBaseUrlArg(String[] args) {
    String found = null;
    for (String arg : args) {
      if (arg.startsWith("--api-base-url=")) {
        found = arg.substring("--api-base-url=".length());
      }
    }
    if (found != null && !found.isBlank()) {
      System.setProperty("api.base.url", found.trim());
    }
  }

  public static void main(String[] args) {
    applyApiBaseUrlArg(args);
    launch(args);
  }
}
