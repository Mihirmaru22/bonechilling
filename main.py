
import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel

app = QApplication(sys.argv)

window = QMainWindow()
window.setWindowTitle("bone chilling")
window.resize(800,500)
window.setCentralWidget(QLabel("Yoo hoo, dog wants a bone"))
window.show()

sys.exit(app.exec())


