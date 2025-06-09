# splash_screen.py
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout, QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie, QColor

class SplashScreen(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setStyleSheet("background-color: white; border-radius: 10px;")

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)

        self.spinner = QLabel()
        self.movie = QMovie("assets/spinner.gif")
        self.spinner.setMovie(self.movie)
        layout.addWidget(self.spinner)

        self.status_label = QLabel("Loading...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; color: #333333;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        self.setFixedSize(300, 200)
        self.movie.start()

        screen_geometry = QApplication.desktop().screenGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def update_status(self, message: str):
        self.status_label.setText(message)
    
    def closeEvent(self, event):
        if self.movie and self.movie.isValid() and self.movie.state() == QMovie.Running:
            self.movie.stop()
        super().closeEvent(event)
