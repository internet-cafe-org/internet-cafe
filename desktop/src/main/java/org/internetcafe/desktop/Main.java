package org.internetcafe.desktop;

import javafx.application.Application;
import javafx.scene.Scene;
import javafx.stage.Stage;
import org.internetcafe.desktop.screens.DashboardScreen;
import org.internetcafe.desktop.screens.EnrollScreen;
import org.internetcafe.desktop.screens.LoginScreen;
import org.internetcafe.desktop.screens.QrScreen;

public class Main extends Application {
    @Override
    public void start(Stage stage) {
        LoginScreen loginScreen = new LoginScreen();
        EnrollScreen enrollScreen = new EnrollScreen();
        QrScreen qrScreen = new QrScreen();
        DashboardScreen dashboardScreen = new DashboardScreen();

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
                    stage.setScene(new Scene(qrScreen.getRoot(), 1280, 800));
                });

        qrScreen.setOnBack(
                () -> {
                    stage.setScene(new Scene(loginScreen.getRoot(), 1280, 800));
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
