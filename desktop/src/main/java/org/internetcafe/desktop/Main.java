package org.internetcafe.desktop;

import javafx.application.Application;
import javafx.scene.Scene;
import javafx.stage.Stage;
import org.internetcafe.desktop.screens.BoardScreen;
import org.internetcafe.desktop.screens.ConnectionStatus;
import org.internetcafe.desktop.screens.DashboardScreen;
import org.internetcafe.desktop.screens.EnrollScreen;
import org.internetcafe.desktop.screens.LoginScreen;
import org.internetcafe.desktop.screens.QrScreen;
import org.internetcafe.desktop.screens.QrScreenModel;
import org.internetcafe.desktop.services.ApiClient;

public class Main extends Application {
  @Override
  public void start(Stage stage) {
    LoginScreen loginScreen = new LoginScreen();
    EnrollScreen enrollScreen = new EnrollScreen();
    QrScreenModel qrModel = new QrScreenModel("LAB1-PC03", "Sala 1", ConnectionStatus.ONLINE, 45);
    QrScreen qrScreen = new QrScreen(qrModel);
    DashboardScreen dashboardScreen = new DashboardScreen();
    BoardScreen boardScreen = new BoardScreen("dev".equals(System.getProperty("app.profile")));
    ApiClient apiClient = new ApiClient();
    String machineCode = System.getProperty("machine.code", qrModel.machineCode());

    Scene scene = new Scene(loginScreen.getRoot(), 1280, 800);
    scene.getStylesheets().add(getClass().getResource("/styles.css").toExternalForm());

    stage.setTitle("Internet Cafe Desktop");
    stage.setScene(scene);
    stage.setMinWidth(900);
    stage.setMinHeight(700);
    stage.show();

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
          qrScreen.stopRotation();
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });

    boardScreen.setOnBackToQr(
        () -> {
          boardScreen.stop();
          qrScreen.startRotation(apiClient, machineCode);
          stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
        });

    qrScreen.setOnApproved(
        (response, approvedAt) -> {
          stage.setScene(new Scene(boardScreen.getRoot(), 1280, 800));
          boardScreen.show(response.displayName(), response.maskedStudentCode(), approvedAt);
        });

    dashboardScreen.setOnLogout(
        () -> {
          stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
        });
  }

  public static void main(String[] args) {
    launch(args);
  }
}
