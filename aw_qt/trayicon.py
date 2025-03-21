import socket
import sys
import logging
import signal
import os
import subprocess
from collections import defaultdict
from typing import Any, DefaultDict, List, Optional, Dict
import webbrowser

from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QApplication,
    QSystemTrayIcon,
    QMessageBox,
    QMenu,
    QWidget,
    QPushButton,
    QAction
)
from PyQt5.QtGui import QIcon

import aw_core
from aw_client import ActivityWatchClient
import urllib.parse
from aw_client.localToken import LocalToken

from .manager import Manager, Module
from .config import AwQtSettings

config = AwQtSettings(testing=False)
logger = logging.getLogger(__name__)
application_domain = config.application_domain

def get_env() -> Dict[str, str]:
    """
    Necessary for xdg-open to work properly when PyInstaller overrides LD_LIBRARY_PATH

    https://github.com/nccasia/komutracker/issues/208#issuecomment-417346407
    """
    env = dict(os.environ)  # make a copy of the environment
    lp_key = "LD_LIBRARY_PATH"  # for GNU/Linux and *BSD.
    lp_orig = env.get(lp_key + "_ORIG")
    if lp_orig is not None:
        env[lp_key] = lp_orig  # restore the original, unmodified value
    else:
        # This happens when LD_LIBRARY_PATH was not set.
        # Remove the env var as a last resort:
        env.pop(lp_key, None)
    return env


def open_url(url: str) -> None:
    if sys.platform == "linux":
        env = get_env()
        subprocess.Popen(["xdg-open", url], env=env)
    else:
        webbrowser.open(url)


def open_webui(root_url: str) -> None:
    print("Opening dashboard")
    open_url(root_url)


def open_apibrowser(root_url: str) -> None:
    print("Opening api browser")
    open_url(root_url + "/api")


def open_dir(d: str) -> None:
    """From: http://stackoverflow.com/a/1795849/965332"""
    if sys.platform == "win32":
        os.startfile(d)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", d])
    else:
        env = get_env()
        subprocess.Popen(["xdg-open", d], env=env)


class TrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        manager: Manager,
        icon: QIcon,
        parent: Optional[QWidget] = None,
        testing: bool = False,
    ) -> None:
        QSystemTrayIcon.__init__(self, icon, parent)
        self._parent = parent  # QSystemTrayIcon also tries to save parent info but it screws up the type info
        self.setToolTip("KomuTracker" + (" (testing)" if testing else ""))

        self.manager = manager
        self.testing = testing

        self.root_url = "http://{app_url}:{port}".format(app_url=application_domain, port=5666 if self.testing else 80)
        self.activated.connect(self.on_activated)

        self._build_rootmenu()

    def on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            open_webui(self.root_url)

    def _build_rootmenu(self) -> None:
        menu = QMenu(self._parent)

        if self.testing:
            menu.addAction("Running in testing mode")  # .setEnabled(False)
            menu.addSeparator()

        # openWebUIIcon = QIcon.fromTheme("open")
        #menu.addAction("Open Dashboard", lambda: open_webui(self.root_url))
        #menu.addAction("Open API Browser", lambda: open_apibrowser(self.root_url))

        menu.addSeparator()

        modulesMenu = menu.addMenu("Modules")
        self._build_modulemenu(modulesMenu)

        #menu.addSeparator()
        menu.addAction(
            "Open log folder", lambda: open_dir(aw_core.dirs.get_log_dir(None))
        )
        menu.addSeparator()

        # Auth
        
        mainAction = menu.addAction(
            "Connecting...", lambda: login(mainAction, logoutAction)
        )
        mainAction.setEnabled(False)
        logoutAction = menu.addAction(
            "Logout", lambda: logout(mainAction, logoutAction)
        )
        logoutAction.setEnabled(False)
        menu.addSeparator()

        exitIcon = QIcon.fromTheme(
            "application-exit", QIcon("media/application_exit.png")
        )
        # This check is an attempted solution to: https://github.com/nccasia/komutracker/issues/62
        # Seems to be in agreement with: https://github.com/OtterBrowser/otter-browser/issues/1313
        #   "it seems that the bug is also triggered when creating a QIcon with an invalid path"
        if exitIcon.availableSizes():
            menu.addAction(exitIcon, "Quit KomuTracker", lambda: exit(self.manager))
        else:
            menu.addAction("Quit KomuTracker", lambda: exit(self.manager))

        self.setContextMenu(menu)

        def show_module_failed_dialog(module: Module) -> None:
            box = QMessageBox(self._parent)
            box.setIcon(QMessageBox.Warning)
            box.setText("Module {} quit unexpectedly".format(module.name))
            box.setDetailedText(module.read_log(self.testing))

            restart_button = QPushButton("Restart", box)
            restart_button.clicked.connect(module.start)
            box.addButton(restart_button, QMessageBox.AcceptRole)
            box.setStandardButtons(QMessageBox.Cancel)

            box.show()

        def rebuild_modules_menu() -> None:
            for action in modulesMenu.actions():
                if action.isEnabled():
                    module: Module = action.data()
                    alive = module.is_alive()
                    action.setChecked(alive)
                    # print(module.text(), alive)

        QtCore.QTimer.singleShot(2000, rebuild_modules_menu)

        def check_module_status() -> None:
            unexpected_exits = self.manager.get_unexpected_stops()
            if unexpected_exits:
                for module in unexpected_exits:
                    show_module_failed_dialog(module)
                    module.stop()

            # TODO: Do it in a better way, singleShot isn't pretty...
            QtCore.QTimer.singleShot(2000, rebuild_modules_menu)

        QtCore.QTimer.singleShot(2000, check_module_status)

        def auth_check() -> None:
            logger.info("begin auth check")
            awc = ActivityWatchClient()
            if awc.localToken.get() is not None and awc.localToken.get() != "":
                logger.info(f"local token found: {awc.localToken.get()}")
                if awc.auth_status == "Success":
                    logger.info(f"user: {awc.user_name} - {awc.user_email}")
                    mainAction.setText(awc.user_name)
                    mainAction.setEnabled(True)
                    logoutAction.setEnabled(True)
                            
                    for action in modulesMenu.actions():
                        if not action.isChecked():
                            module: Module = action.data()
                            if module is not None:
                                module.start(testing=self.testing)
                                action.setChecked(True)
                    logger.info(f"register auth check in next 60s")
                    QtCore.QTimer.singleShot(60000, auth_check)
                elif awc.auth_status == "Failed":
                    logger.info(f"stopping services")
                    QMessageBox.critical(
                        None,
                        "Komutracker",
                        "Please re-lauch the application and login again!",
                    )
                    for action in modulesMenu.actions():
                        if action.isChecked():
                            module: Module = action.data()
                            if module is not None:
                                module.stop()
                                action.setChecked(False)
                    awc.localToken.delete()
                    sys.exit(1)
                else:
                    logger.info(f"auth status: {awc.auth_status}")
                    logger.info(f"register auth check in next 5s")
                    mainAction.setText('Login')
                    awc.localToken.delete()
                    mainAction.setEnabled(True)
                    logoutAction.setEnabled(False)
                    QtCore.QTimer.singleShot(5000, auth_check)
            else:
                logger.info(f"No local token found, getting token from server ...")
                awc.get_device_token(mainAction, logoutAction)
                QtCore.QTimer.singleShot(5000, auth_check)
                
        auth_check()
    
    def _build_modulemenu(self, moduleMenu: QMenu) -> None:
        moduleMenu.clear()

        def add_module_menuitem(module: Module) -> None:
            title = module.name
            ac = moduleMenu.addAction(title, lambda: module.toggle(self.testing))

            ac.setData(module)
            ac.setCheckable(True)
            ac.setChecked(module.is_alive())

        for location, modules in [
            ("bundled", self.manager.modules_bundled),
            ("system", self.manager.modules_system),
        ]:
            header = moduleMenu.addAction(location)
            header.setEnabled(False)

            for module in sorted(modules, key=lambda m: m.name):
                add_module_menuitem(module)


def exit(manager: Manager) -> None:
    # TODO: Do cleanup actions
    # TODO: Save state for resume
    print("Shutdown initiated, stopping all services...")
    manager.stop_all()
    # Terminate entire process group, just in case.
    # os.killpg(0, signal.SIGINT)

    QApplication.quit()


def run(manager: Manager, testing: bool = False) -> Any:
    logger.info("Creating trayicon...")
    # print(QIcon.themeSearchPaths())

    app = QApplication(sys.argv)

    # Without this, Ctrl+C will have no effect
    signal.signal(signal.SIGINT, lambda *args: exit(manager))
    # Ensure cleanup happens on SIGTERM
    signal.signal(signal.SIGTERM, lambda *args: exit(manager))

    # Allow pixmaps (e.g. trayicon) to use higher DPI images to make icons less
    # blurry when fractional scaling is used
    app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

    timer = QtCore.QTimer()
    timer.start(100)  # You may change this if you wish.
    timer.timeout.connect(lambda: None)  # Let the interpreter run each 500 ms.

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "Systray",
            "I couldn't detect any system tray on this system. Either get one or run the KomuTracker modules from the console.",
        )
        sys.exit(1)

    widget = QWidget()
    if sys.platform == "darwin":
        icon = QIcon(":/black-monochrome-logo.png")
        # Allow macOS to use filters for changing the icon's color
        # icon.setIsMask(True)
    else:
        icon = QIcon(":/logo.png")

    trayIcon = TrayIcon(manager, icon, widget, testing=testing)
    trayIcon.show()

    QApplication.setQuitOnLastWindowClosed(False)

    logger.info("Initialized aw-qt and trayicon succesfully")
    # Run the application, blocks until quit
    return app.exec_()

def login(mainAction: QAction, logoutAction: QAction) -> Any:
    awc = ActivityWatchClient()
    if awc.auth_status == "Success":
        open_url(f"http://{application_domain}/#/activity/{awc.client_hostname}/view/")
    else:
        awc.localToken.delete()
        mainAction.setText('Authenticating...')
        mainAction.setEnabled(False)
        logoutAction.setEnabled(False)

        authUrl = config.oauth2_auth_url
        clientId = config.oauth2_client_id
        redirect_url = urllib.parse.quote(config.oauth2_redirect_uri)
        state = f"{os.getlogin()}_{socket.gethostname()}"
        open_url(f"{authUrl}/oauth2/auth?client_id={clientId}&redirect_uri={redirect_url}&response_type=code&scope=openid+offline&state={state}")

def logout(mainAction: QAction, logoutAction: QAction) -> Any:
    awc = ActivityWatchClient()
    awc.delete_device_token(mainAction, logoutAction)