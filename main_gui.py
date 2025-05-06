import sys
import os
import webbrowser
import requests
import winreg
import shutil

from PyQt6 import QtWidgets, QtCore, QtGui

from PyQt6.QtCore import Qt


# Import the MultiSelectComboBox from the package
from lib.multiselect_combobox import MultiSelectComboBox
from lib.uploader import upload_to_youtube, get_playlists, get_channel_info, revoke_auth

EXTENSIONS = [".mp4", ".mkv"]

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)


def get_appdata_dir():
    appdata = os.environ.get("APPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming"
    )
    folder = os.path.join(appdata, "YouTubeUploader")
    os.makedirs(folder, exist_ok=True)
    return folder


def ensure_extracted_icon() -> str:
    if getattr(sys, 'frozen', False):
        appdata_dir = get_appdata_dir()
        final_icon_path = os.path.join(appdata_dir, "yt.ico")

        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        embedded_icon = os.path.join(base_path, "lib", "yt.ico")

        if not os.path.exists(final_icon_path):
            shutil.copyfile(embedded_icon, final_icon_path)
        return final_icon_path
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(script_dir, "lib", "yt.ico")


def add_shellex():
    """
    Adds 'Upload to YouTube' context menu for .mp4 and .mkv files
    """
    icon_path = ensure_extracted_icon()

    if getattr(sys, 'frozen', False):
        app_command = f'"{sys.executable}" "%1"'
    else:
        script_path = os.path.abspath(__file__)
        pythonw_path = sys.executable.replace("python.exe", "pythonw.exe")
        app_command = f'"{pythonw_path}" "{script_path}" "%1"'

    for ext in EXTENSIONS:
        try:
            base_key_path = fr"Software\Classes\SystemFileAssociations\{ext}\shell\Upload to YouTube"
            command_key_path = base_key_path + r"\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_key_path) as key:
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, icon_path)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, app_command)
            print(f"Shell integration added for {ext}")
        except Exception as e:
            print(f"Error adding registry key for {ext}: {e}")


def remove_shellex():
    """
    Removes the 'Upload to YouTube' context menu entries for .mp4 and .mkv files
    """
    for ext in EXTENSIONS:
        try:
            base_key_path = fr"Software\Classes\SystemFileAssociations\{ext}\shell\Upload to YouTube"
            command_key_path = base_key_path + r"\command"
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, command_key_path)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base_key_path)
            print(f"Removed shell integration for {ext}")
        except Exception as e:
            print(f"Error removing registry key for {ext}: {e}")


# Worker to run the upload in a separate thread.
class UploadWorker(QtCore.QObject):
    progress_update = QtCore.pyqtSignal(object)  # Emits UploadStatus object
    finished = QtCore.pyqtSignal(object)         # Emits UploadStatus on finish
    error = QtCore.pyqtSignal(str)

    def __init__(self, file_path, playlist_ids, privacy, title, description, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.playlist_ids = playlist_ids  # Now a list of playlist IDs.
        self.privacy = privacy
        self.title = title
        self.description = description

    def report_progress(self, status):
        self.progress_update.emit(status)

    def run(self):
        try:
            status = upload_to_youtube(
                file_path=self.file_path,
                playlist_ids=self.playlist_ids,  # uploader now accepts a list
                privacy=self.privacy,
                title=self.title,
                description=self.description,
                debug=False,
                callback=self.report_progress,
            )
            if status.step == "Finished":
                self.finished.emit(status)
            else:
                self.error.emit(status.error or "Upload did not finish successfully.")
        except Exception as e:
            self.error.emit(str(e))


# Worker to run the authentication in a separate thread.
class AuthWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()             # Emits when auth is done (success or fail)
    error = QtCore.pyqtSignal(str)               # Emits if there's an authentication error
    channel_info_ready = QtCore.pyqtSignal(dict) # Emits the channel info

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            from lib.uploader import authenticate, get_channel_info
            authenticate()
            channel_info = get_channel_info()
            if channel_info:
                self.channel_info_ready.emit(channel_info)
            else:
                self.error.emit("Could not retrieve channel information.")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class ProfileImageWorker(QtCore.QObject):
    image_loaded = QtCore.pyqtSignal(QtGui.QPixmap)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            resp = requests.get(self.url)
            if resp.status_code == 200:
                pixmap = QtGui.QPixmap()
                pixmap.loadFromData(resp.content)
                self.image_loaded.emit(pixmap)
            else:
                self.error.emit(f"Error loading image: {resp.status_code}")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class PlaylistsWorker(QtCore.QObject):
    playlists_loaded = QtCore.pyqtSignal(list)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    
    def run(self):
        try:
            playlists = get_playlists()
            self.playlists_loaded.emit(playlists)
        except Exception as e:
            self


class SegmentedProgressBar(QtWidgets.QProgressBar):
    def __init__(self, segments=20, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.segments = segments
        self.setTextVisible(False)
        self.setMinimum(0)
        self.setMaximum(100)
        self.setValue(0)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        rectF = QtCore.QRectF(rect)

        radius = 10
        painter.setPen(QtGui.QColor("#555"))
        painter.setBrush(QtGui.QColor("#3c3c3c"))
        painter.drawRoundedRect(rectF, radius, radius)

        path = QtGui.QPainterPath()
        path.addRoundedRect(rectF, radius, radius)
        painter.setClipPath(path)

        metrics = QtGui.QFontMetrics(self.font())
        char_width = metrics.horizontalAdvance("M")
        char_height = metrics.height()

        spacing = 1
        total_width = self.segments * char_width + (self.segments - 1) * spacing
        start_x = (rect.width() - total_width) / 2 if rect.width() > total_width else 0
        start_y = (rect.height() - char_height) / 2 if rect.height() > char_height else 0

        total_range = self.maximum() - self.minimum()
        progress_ratio = (self.value() - self.minimum()) / total_range if total_range != 0 else 0
        num_filled = int(self.segments * progress_ratio + 0.5)

        for i in range(self.segments):
            x = start_x + i * (char_width + spacing)
            block_rect = QtCore.QRectF(x, start_y, char_width, char_height)
            if i < num_filled:
                painter.setBrush(QtGui.QColor("#05B8CC"))
            else:
                painter.setBrush(QtGui.QColor("#2b2b2b"))
            painter.drawRect(block_rect)
        painter.end()


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(500, 380)
        self.setWindowTitle("YouTube Uploader")

        icon_path = resource_path("lib/yt.ico")
        self.setWindowIcon(QtGui.QIcon(icon_path))

        self.full_file_path = ""
        self.upload_in_progress = False
        self.auth_in_progress = False  # Keep track of authentication

        self.setupUI()
        self.applyStyle()
        self.start_authentication()

    def setupUI(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        uniform_height = 30

        # Title row: Title field on the left, channel info on the right.
        title_layout = QtWidgets.QHBoxLayout()
        self.lineEdit = QtWidgets.QLineEdit(self)
        self.lineEdit.setPlaceholderText("Title...")
        self.lineEdit.setFixedWidth(300)
        self.lineEdit.setFixedHeight(uniform_height)
        title_layout.addWidget(self.lineEdit)

        # Channel info widget: channel name and profile picture.
        self.channelWidget = QtWidgets.QWidget(self)
        self.channelWidget.setFixedHeight(uniform_height)
        ch_layout = QtWidgets.QHBoxLayout(self.channelWidget)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        self.channelName = QtWidgets.QLabel("Authenticating...", self)
        font = self.channelName.font()
        font.setBold(True)
        self.channelName.setFont(font)
        ch_layout.addWidget(self.channelName)
        self.channelPic = QtWidgets.QLabel(self)
        self.channelPic.setFixedSize(uniform_height, uniform_height)
        self.channelPic.setScaledContents(True)
        ch_layout.addWidget(self.channelPic)
        self.channelWidget.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.channelWidget.customContextMenuRequested.connect(self.show_channel_menu)
        title_layout.addWidget(self.channelWidget)
        main_layout.addLayout(title_layout)

        # Description field.
        self.textBox = QtWidgets.QTextEdit(self)
        self.textBox.setPlaceholderText("Description...")
        self.textBox.setText("Uploaded via YouTube Uploader Library")
        main_layout.addWidget(self.textBox)

        # File selection row.
        file_layout = QtWidgets.QHBoxLayout()
        self.selectFileButton = QtWidgets.QPushButton("Select File", self)
        self.selectFileButton.setFixedHeight(uniform_height)
        self.selectFileButton.clicked.connect(self.select_file)
        file_layout.addWidget(self.selectFileButton)
        self.filePathDisplay = QtWidgets.QLineEdit(self)
        self.filePathDisplay.setReadOnly(True)
        self.filePathDisplay.setFixedHeight(uniform_height)
        file_layout.addWidget(self.filePathDisplay)
        main_layout.addLayout(file_layout)

        # Progress row.
        progress_layout = QtWidgets.QHBoxLayout()
        self.statusLabel = QtWidgets.QLabel("Idle", self)
        self.statusLabel.setFixedWidth(120)
        self.statusLabel.setFixedHeight(uniform_height)
        self.statusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font_status = self.statusLabel.font()
        font_status.setBold(True)
        self.statusLabel.setFont(font_status)
        progress_layout.addWidget(self.statusLabel)
        self.progressBar = SegmentedProgressBar(segments=20, parent=self)
        self.progressBar.setFixedHeight(uniform_height)
        progress_layout.addWidget(self.progressBar, 1)
        self.progressNumber = QtWidgets.QLabel("0%", self)
        self.progressNumber.setFixedWidth(50)
        self.progressNumber.setFixedHeight(uniform_height)
        self.progressNumber.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font_number = self.progressNumber.font()
        font_number.setBold(True)
        self.progressNumber.setFont(font_number)
        progress_layout.addWidget(self.progressNumber)
        main_layout.addLayout(progress_layout)

        # Upload controls row: visibility dropdown, playlist multiselect, Upload button.
        upload_layout = QtWidgets.QHBoxLayout()
        self.visibilityCombo = QtWidgets.QComboBox(self)
        self.visibilityCombo.setFixedHeight(uniform_height)
        self.visibilityCombo.setFixedWidth(100)
        self.visibilityCombo.addItems(["Private", "Unlisted", "Public"])
        self.visibilityCombo.setCurrentIndex(1)
        upload_layout.addWidget(self.visibilityCombo)
        
        self.playlistCombo = MultiSelectComboBox(self)
        self.playlistCombo.setFixedHeight(uniform_height)
        self.playlistCombo.setPlaceholderText("Loading...")


        self.playlistCombo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.playlistCombo.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        upload_layout.addWidget(self.playlistCombo)
        
        self.uploadButton = QtWidgets.QPushButton("Upload", self)
        self.uploadButton.setFixedHeight(uniform_height)
        self.uploadButton.clicked.connect(self.upload_video)
        self.uploadButton.setEnabled(False)  # Disable until authenticated.
        upload_layout.addWidget(self.uploadButton)
        main_layout.addLayout(upload_layout)

        # Video URL row.
        url_layout = QtWidgets.QHBoxLayout()
        self.urlDisplay = QtWidgets.QLineEdit(self)
        self.urlDisplay.setReadOnly(True)
        self.urlDisplay.setFixedHeight(uniform_height)
        self.urlDisplay.setPlaceholderText("Youtube Video URL")
        url_layout.addWidget(self.urlDisplay)
        self.copyButton = QtWidgets.QPushButton("Copy", self)
        self.copyButton.setFixedHeight(uniform_height)
        self.copyButton.clicked.connect(self.copy_url)
        url_layout.addWidget(self.copyButton)
        self.openButton = QtWidgets.QPushButton("Open", self)
        self.openButton.setFixedHeight(uniform_height)
        self.openButton.clicked.connect(self.open_browser)
        url_layout.addWidget(self.openButton)
        main_layout.addLayout(url_layout)

    def applyStyle(self):
        styleSheet = """
        QWidget {
            background-color: #2b2b2b;
            color: #f0f0f0;
            font-size: 14px;
        }
        QLineEdit, QTextEdit, QLabel, QProgressBar {
            border: 2px solid #555;
            border-radius: 10px;
            padding: 5px;
            background-color: #3c3c3c;
        }
        QPushButton {
            background-color: #5a5a5a;
            font-weight: bold;
            border: 2px solid #555;
            border-radius: 10px;
            padding: 5px;
        }
        QPushButton:hover {
            background-color: #707070;
        }
        QPushButton::pressed {
            background-color: #404040;
        }
        QComboBox {
            font-weight: bold;
        }
        QProgressBar::chunk {
            background-color: #fd5a5a;
            border-radius: 10px;
        }
        """
        self.setStyleSheet(styleSheet)

   

    def start_authentication(self):
        self.authThread = QtCore.QThread()
        self.authWorker = AuthWorker()
        self.authWorker.moveToThread(self.authThread)
        self.authThread.started.connect(self.authWorker.run)
        self.authWorker.finished.connect(self.authThread.quit)
        self.authWorker.finished.connect(self.authWorker.deleteLater)
        self.authThread.finished.connect(self.authThread.deleteLater)
        self.authWorker.channel_info_ready.connect(self.on_channel_info_ready)
        self.authWorker.error.connect(self.on_auth_error)
        self.authThread.start()
        self.auth_in_progress = True

    def on_channel_info_ready(self, info):
        # Update channel name immediately.
        self.channelName.setText(info.get("title", "Unknown"))
        
        # Start a thread to load the profile image.
        profile_url = info.get("profile_image", "")
        if profile_url:
            self.profileThread = QtCore.QThread()
            self.profileWorker = ProfileImageWorker(profile_url)
            self.profileWorker.moveToThread(self.profileThread)
            self.profileThread.started.connect(self.profileWorker.run)
            self.profileWorker.image_loaded.connect(self.channelPic.setPixmap)
            self.profileWorker.error.connect(lambda e: print("Profile image error:", e))
            self.profileWorker.finished.connect(self.profileThread.quit)
            self.profileWorker.finished.connect(self.profileWorker.deleteLater)
            self.profileThread.finished.connect(self.profileThread.deleteLater)
            self.profileThread.start()
        else:
            self.channelPic.clear()
        
        # Start a thread to load playlists.
        self.playlistsThread = QtCore.QThread()
        self.playlistsWorker = PlaylistsWorker()
        self.playlistsWorker.moveToThread(self.playlistsThread)
        self.playlistsThread.started.connect(self.playlistsWorker.run)
        self.playlistsWorker.playlists_loaded.connect(self.handle_playlists)
        self.playlistsWorker.error.connect(lambda e: print("Playlists error:", e))
        self.playlistsWorker.finished.connect(self.playlistsThread.quit)
        self.playlistsWorker.finished.connect(self.playlistsWorker.deleteLater)
        self.playlistsThread.finished.connect(self.playlistsThread.deleteLater)
        self.playlistsThread.start()
        
        self.uploadButton.setEnabled(True)
        self.auth_in_progress = False

    def handle_playlists(self, playlists):
        self.playlistCombo.clear()
        for pl in playlists:
            title = pl["snippet"]["title"]
            playlist_id = pl["id"]
            self.playlistCombo.addItem(title, playlist_id)

        self.playlistCombo.setPlaceholderText("Select Playlists")
        self.playlistCombo.updateText()


    def on_auth_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Auth Error", message)
        self.channelName.setText("Auth Failed")
        self.channelPic.clear()
        self.auth_in_progress = False

    def populate_playlists(self):
        try:
            playlists = get_playlists()
            self.playlistCombo.clear()
            for pl in playlists:
                title = pl["snippet"]["title"]

                playlist_id = pl["id"]
                self.playlistCombo.addItem(title, playlist_id)
                
            self.playlistCombo.updateText()
        except Exception as e:
            print(f"Error retrieving playlists: {e}")
            self.playlistCombo.clear()


    def update_channel_info(self, info=None):
        if info is None:
            info = get_channel_info()
        if info:
            self.channelName.setText(info.get("title", "Unknown"))
            try:
                resp = requests.get(info.get("profile_image", ""))
                if resp.status_code == 200:
                    pixmap = QtGui.QPixmap()
                    pixmap.loadFromData(resp.content)
                    self.channelPic.setPixmap(pixmap)
                else:
                    self.channelPic.clear()
            except Exception as e:
                print("Error loading profile image:", e)
                self.channelPic.clear()
        else:
            self.channelName.setText("Not Signed In")
            self.channelPic.clear()

    def show_channel_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #3c3c3c;
                border: 2px solid #555;
                border-radius: 10px;
                padding: 5px;
                color: #f0f0f0;
            }
            QMenu::item {
                padding: 5px 25px;
                background-color: transparent;
                border-radius: 8px;  /* Add this to make selection look rounded */
            }
            QMenu::item:selected {
                background-color: #fd5a5a;
                border-radius: 8px;  /* Rounded corners on selection */
            }
            """
        )

        if self.channelName.text() in ["Not Signed In", "Auth Failed"]:
            action = menu.addAction("Sign In")
        else:
            action = menu.addAction("Log Out")
            if self.auth_in_progress:
                action.setEnabled(False)
        global_pos = self.channelWidget.mapToGlobal(pos)
        global_main_rect = QtCore.QRect(self.mapToGlobal(QtCore.QPoint(0, 0)), self.size())
        menu_size = menu.sizeHint()
        if global_pos.x() + menu_size.width() > global_main_rect.right():
            global_pos.setX(global_main_rect.right() - menu_size.width())
        if global_pos.y() + menu_size.height() > global_main_rect.bottom():
            global_pos.setY(global_main_rect.bottom() - menu_size.height())
        selected = menu.exec(global_pos)
        if selected == action:
            if self.channelName.text() in ["Not Signed In", "Auth Failed"]:
                self.start_authentication()
            else:
                if revoke_auth():
                    self.channelName.setText("Not Signed In")
                    self.channelPic.clear()
                    self.playlistCombo.clear()
                    self.playlistCombo.lineEdit().clear()

    def select_file(self):
        if self.upload_in_progress:
            QtWidgets.QMessageBox.warning(
                self, "Upload in Progress", "Cannot select a new file while upload is in progress."
            )
            return
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mkv)"
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, file_path: str):
        self.full_file_path = file_path
        base = os.path.basename(file_path)
        self.filePathDisplay.setText(base)
        self.filePathDisplay.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        title, _ = os.path.splitext(base)
        self.lineEdit.setText(title)
        self.textBox.clear()
        self.urlDisplay.clear()
        self.statusLabel.setText("Idle")
        self.progressBar.setValue(0)
        self.progressNumber.setText("0%")

    def copy_url(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.urlDisplay.text())

    def open_browser(self):
        url = self.urlDisplay.text().strip()
        if url:
            webbrowser.open(url)

    def upload_video(self):
        if not self.full_file_path:
            return
        title = self.lineEdit.text().strip()
        description = self.textBox.toPlainText().strip()
        privacy = self.visibilityCombo.currentText().lower()
        # Retrieve the list of selected playlist IDs using currentData().
        playlist_ids = self.playlistCombo.currentData()

        self.uploadButton.setEnabled(False)
        self.upload_in_progress = True
        self.statusLabel.setText("Uploading...")

        self.uploadThread = QtCore.QThread()
        self.uploadWorker = UploadWorker(
            file_path=self.full_file_path,
            playlist_ids=playlist_ids,
            privacy=privacy,
            title=title,
            description=description,
        )
        self.uploadWorker.moveToThread(self.uploadThread)
        self.uploadThread.started.connect(self.uploadWorker.run)
        self.uploadWorker.progress_update.connect(self.handle_progress_update)
        self.uploadWorker.finished.connect(self.handle_upload_finished)
        self.uploadWorker.error.connect(self.handle_upload_error)
        self.uploadWorker.finished.connect(self.uploadThread.quit)
        self.uploadWorker.finished.connect(self.uploadWorker.deleteLater)
        self.uploadThread.finished.connect(self.uploadThread.deleteLater)
        self.uploadThread.start()

    def handle_progress_update(self, status):
        color_map = {
            "Uploading": "#ff9800",
            "Processing": "#2196f3",
            "Verifying": "#9c27b0",
            "Finished": "#4caf50",
            "Error": "#f44336",
        }
        step = status.step
        self.statusLabel.setText(step)
        self.statusLabel.setStyleSheet(
            "color: {}; background-color: transparent;".format(color_map.get(step, "#ffffff"))
        )
        if step == "Uploading":
            self.progressBar.setValue(status.progress)
            self.progressNumber.setText(f"{status.progress}%")
        else:
            self.progressBar.setValue(100)
            self.progressNumber.setText("100%")
        if status.video_url:
            self.urlDisplay.setText(status.video_url)

    def handle_upload_finished(self, status):
        self.handle_progress_update(status)
        self.uploadButton.setEnabled(True)
        self.upload_in_progress = False

    def handle_upload_error(self, error_msg):
        QtWidgets.QMessageBox.critical(self, "Upload Error", error_msg)
        self.uploadButton.setEnabled(True)
        self.upload_in_progress = False


if __name__ == "__main__":
    if any(arg in sys.argv for arg in ["--help", "-h"]):
        print("""
    Usage: python uploader.py [options/video file]

    Options:
    -h, --help      Display this help message and exit.
    -s, --shell     Add shell integration. This adds a right-click "Upload to YouTube" option for supported video file types.
    -r, --rshell    Remove shell integration.

    If a video file is passed as an argument, the application will load that file automatically.
    """)

        sys.exit(0)
    if any(arg in sys.argv for arg in ["--shell", "-s"]):
        add_shellex()
        print("Shell integration added.")
        sys.exit(0)
    if any(arg in sys.argv for arg in ["--rshell", "-r"]):
        remove_shellex()
        print("Shell integration removed.")
        sys.exit(0)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("YouTube Uploader")
    window = MainWindow()
    if len(sys.argv) > 1:
        arg_file = sys.argv[1]
        if any(arg_file.lower().endswith(ext) for ext in EXTENSIONS):
            window.set_file_path(arg_file)
    window.show()
    sys.exit(app.exec())
