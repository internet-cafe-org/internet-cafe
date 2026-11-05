package org.internetcafe.desktop;

import java.awt.AWTException;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.GraphicsEnvironment;
import java.awt.Image;
import java.awt.MenuItem;
import java.awt.PopupMenu;
import java.awt.RenderingHints;
import java.awt.SystemTray;
import java.awt.TrayIcon;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.image.BufferedImage;
import java.util.logging.Logger;

/**
 * System tray icon shown while the machine is in passive mode.
 *
 * <p>AWT invokes the callbacks on its own thread; callers must hop to the JavaFX thread (for
 * example with {@code Platform.runLater}) before touching the UI.
 */
public final class TrayManager {

  private static final Logger log = Logger.getLogger(TrayManager.class.getName());
  private static final int ICON_SIZE_PX = 32;

  private final String tooltip;
  private final Runnable onOpen;
  private final Runnable onRegisterAccess;
  private TrayIcon trayIcon;

  /**
   * Creates the manager without touching the tray yet.
   *
   * @param tooltip text shown when the pointer rests on the icon
   * @param onOpen called when the icon is clicked with the left button
   * @param onRegisterAccess called when "Registrar acceso" is chosen in the icon menu
   */
  public TrayManager(String tooltip, Runnable onOpen, Runnable onRegisterAccess) {
    if (tooltip == null || onOpen == null || onRegisterAccess == null) {
      throw new IllegalArgumentException("Tray dependencies must not be null");
    }
    this.tooltip = tooltip;
    this.onOpen = onOpen;
    this.onRegisterAccess = onRegisterAccess;
  }

  /** Adds the icon to the system tray. Returns {@code false} when the tray is unavailable. */
  public synchronized boolean install() {
    if (trayIcon != null) {
      return true;
    }
    if (GraphicsEnvironment.isHeadless() || !SystemTray.isSupported()) {
      log.warning("System tray is not supported on this machine");
      return false;
    }

    PopupMenu menu = new PopupMenu();
    MenuItem registerItem = new MenuItem("Registrar acceso");
    registerItem.addActionListener(event -> onRegisterAccess.run());
    menu.add(registerItem);

    TrayIcon icon = new TrayIcon(createIcon(), tooltip, menu);
    icon.setImageAutoSize(true);
    icon.addMouseListener(
        new MouseAdapter() {
          @Override
          public void mouseClicked(MouseEvent event) {
            if (event.getButton() == MouseEvent.BUTTON1) {
              onOpen.run();
            }
          }
        });

    try {
      SystemTray.getSystemTray().add(icon);
    } catch (AWTException e) {
      log.warning("Could not add the tray icon: " + e.getMessage());
      return false;
    }
    trayIcon = icon;
    return true;
  }

  /** Removes the icon from the tray. Safe to call more than once. */
  public synchronized void remove() {
    if (trayIcon == null) {
      return;
    }
    SystemTray.getSystemTray().remove(trayIcon);
    trayIcon = null;
  }

  /** Returns {@code true} while the icon is in the tray. */
  public synchronized boolean isInstalled() {
    return trayIcon != null;
  }

  private static Image createIcon() {
    BufferedImage image =
        new BufferedImage(ICON_SIZE_PX, ICON_SIZE_PX, BufferedImage.TYPE_INT_ARGB);
    Graphics2D g = image.createGraphics();
    try {
      g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
      g.setColor(new Color(0x25, 0x63, 0xEB));
      g.fillRoundRect(2, 2, ICON_SIZE_PX - 4, ICON_SIZE_PX - 4, 10, 10);
      g.setColor(Color.WHITE);
      g.fillRect(8, 8, 7, 7);
      g.fillRect(17, 8, 7, 7);
      g.fillRect(8, 17, 7, 7);
      g.fillRect(19, 19, 4, 4);
    } finally {
      g.dispose();
    }
    return image;
  }
}