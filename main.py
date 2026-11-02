import sys
from PySide6.QtWidgets import QApplication, QMainWindow

from import_page import ImportPage

app = QApplication(sys.argv)

window = QMainWindow()
window.setWindowTitle("BoneChilling — Orthopedic Radiology Workstation")
window.resize(1280, 800)

# Put the ImportPage inside the main window
window.setCentralWidget(ImportPage())

window.show()
sys.exit(app.exec())
