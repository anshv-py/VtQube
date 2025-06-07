from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

def create_stat_card(title: str, value: str, color: str) -> QFrame:
    card = QFrame()
    card.setFrameStyle(QFrame.StyledPanel)
    afps = QApplication.instance().font().pointSize() if QApplication.instance() else 10
    card.setStyleSheet(f"""
        QFrame {{
            background-color: {color};
            border-radius: 10px;
            padding: 15px; /* Adjusted padding for better fit */
            margin: 5px;
            min-width: 180px; /* Increased minimum width to prevent text overflow */
        }}
        QLabel {{
            color: white;
            font-weight: bold;
        }}
    """)

    layout = QVBoxLayout()
    card.setLayout(layout)

    title_label = QLabel(title)
    title_label.setAlignment(Qt.AlignCenter)
    title_label.setStyleSheet(f"font-size: {int(afps * 1.2)}pt;") # Slightly increased font size for title

    value_label = QLabel(value)
    value_label.setAlignment(Qt.AlignCenter)
    value_label.setStyleSheet(f"font-size: {int(afps * 2.0)}pt; font-weight: bold;") # Slightly increased font size for value
    # Set an object name so it can be found later for updates
    value_label.setObjectName(f"{title.lower().replace(' ', '_').replace('%', '')}_value")

    layout.addWidget(title_label)
    layout.addWidget(value_label)

    return card
