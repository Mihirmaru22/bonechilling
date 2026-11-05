"""import_page.py — Clean, professional, high-performance workstation for orthopedic X-ray studies."""
import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QRect, QTimer, QUrl
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QSplitter, QTextEdit,
    QLineEdit, QStackedWidget, QFrame, QButtonGroup, QFileDialog,
    QStyledItemDelegate, QStyle, QScrollArea, QSizePolicy, QMenu,
    QCheckBox, QDialog, QAbstractItemView, QMessageBox
)

from worker import IngestionQueueWorker, discover_patient_folders, PipelineWorker
from db import connect, get_patients_summary, update_patient_review

# Modern, authentic medical dark theme (distinct surfaces/shades, minimal boxes, high legibility)
WORKSTATION_STYLE = """
QWidget {
    background-color: #0c0d12;
    color: #e2e8f0;
    font-size: 13px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

QLabel {
    border: none;
    background: transparent;
}

/* Toolbar & Action Buttons */
QPushButton {
    background-color: #181b26;
    color: #f1f5f9;
    border: 1px solid #232838;
    border-radius: 6px;
    padding: 5px 13px;
    font-weight: 500;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #222638;
    border-color: #3b4258;
}
QPushButton:pressed {
    background-color: #12141c;
    border-color: #2563eb;
}
QPushButton:disabled {
    background-color: #13151c;
    color: #4b5563;
    border-color: #1a1d26;
}

/* Search bar */
QLineEdit {
    background-color: #12141c;
    border: 1px solid #1e2230;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #3b82f6;
    background-color: #161924;
}

/* Segmented View Switcher Buttons */
QPushButton#tabBtn {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px 14px;
    font-size: 12px;
    color: #94a3b8;
    font-weight: 500;
}
QPushButton#tabBtn:hover {
    background-color: #1c2130;
    color: #ffffff;
}
QPushButton#tabBtn:checked {
    background-color: #2563eb;
    border: none;
    color: #ffffff;
    font-weight: 600;
}

/* Patient List Sidebar */
QListWidget#patientList {
    background-color: #12141c;
    border: 1px solid #1e2230;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget#patientList::item {
    border: none;
    padding: 0px;
    margin: 0px;
}

/* Projection film strip pills */
QPushButton#filmBtn {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 5px 13px;
    font-size: 12px;
    color: #94a3b8;
    font-weight: 500;
}
QPushButton#filmBtn:hover {
    background-color: #1c2130;
    color: #ffffff;
}
QPushButton#filmBtn:pressed {
    background-color: #172554;
}
QPushButton#filmBtn:checked {
    background-color: #2563eb;
    border: none;
    color: #ffffff;
    font-weight: 600;
}

QLabel#sectionTitle {
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
}

/* Progress bar */
QProgressBar {
    background-color: #12141c;
    border: 1px solid #1e2230;
    border-radius: 5px;
    height: 16px;
    text-align: center;
    color: #cbd5e1;
    font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
    border-radius: 4px;
}

/* Table */
QTableWidget {
    background-color: #12141c;
    alternate-background-color: #151722;
    gridline-color: #1a1d28;
    border: 1px solid #1e2230;
    border-radius: 8px;
    selection-background-color: #1c2438;
    selection-color: #ffffff;
}
QTableWidget::item {
    padding: 6px 10px;
    border: none;
}
QTableWidget::item:selected {
    background-color: #1c2438;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #181b26;
    color: #94a3b8;
    font-weight: 600;
    font-size: 11px;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid #1e2230;
    border-right: 1px solid #1a1d28;
}
"""


def format_views(views_raw):
    """Format JSON or string views cleanly, e.g. ['AP', 'LAT'] -> AP, LAT"""
    if not views_raw:
        return ""
    if isinstance(views_raw, str):
        views_raw = views_raw.strip()
        if views_raw.startswith("["):
            try:
                parsed = json.loads(views_raw)
                if isinstance(parsed, list):
                    return ", ".join(str(x) for x in parsed)
            except Exception:
                pass
        return views_raw.replace('"', '').replace("'", "")
    elif isinstance(views_raw, list):
        return ", ".join(str(x) for x in views_raw)
    return str(views_raw)


class PatientCardDelegate(QStyledItemDelegate):
    """
    High-performance, native QPainter delegate for patient worklist items.
    Eliminates intermediate QWidgets and child QLabels so 100% of mouse clicks
    register instantly with 0ms event latency.
    """
    def sizeHint(self, option, index):
        return QSize(280, 72)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        data = index.data(Qt.UserRole)
        if not data:
            super().paint(painter, option, index)
            painter.restore()
            return

        rect = option.rect.adjusted(3, 2, -3, -2)
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover = bool(option.state & QStyle.State_MouseOver)

        # Shades instead of repetitive boxes:
        if is_selected:
            # Elevated midnight blue-slate surface for active patient
            painter.setBrush(QColor("#1c2438"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 6, 6)

            # Crisp azure accent indicator bar on left edge
            painter.setBrush(QColor("#3b82f6"))
            painter.drawRoundedRect(QRect(rect.left() + 2, rect.top() + 6, 3, rect.height() - 12), 2, 2)
        elif is_hover:
            # Subtle transparent wash on hover (no box border)
            painter.setBrush(QColor("#181c28"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 6, 6)
        else:
            # Unselected: clean flat surface, subtle bottom divider line
            painter.setPen(QPen(QColor("#1a1d28"), 1))
            painter.drawLine(rect.left() + 12, rect.bottom(), rect.right() - 12, rect.bottom())

        # Line 1: Patient Name (Bold, white)
        name_font = QFont(option.font)
        name_font.setBold(True)
        name_font.setPointSize(10)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff") if is_selected else QColor("#e2e8f0"))
        name_rect = QRect(rect.left() + 14, rect.top() + 8, rect.width() - 24, 18)
        name_text = data.get("name", "Unknown Patient")
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, name_text)

        # Line 2: Demographics (Age/Sex, ID, Film count)
        sub_font = QFont(option.font)
        sub_font.setPointSize(9)
        painter.setFont(sub_font)
        painter.setPen(QColor("#94a3b8") if is_selected else QColor("#64748b"))
        sub_rect = QRect(rect.left() + 14, rect.top() + 28, rect.width() - 24, 16)
        sub_text = f"{data.get('age_sex', '')} · ID: {data.get('hospital_id', '')} · {data.get('film_count', 0)} films"
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter, sub_text)

        # Line 3: Anatomy Tags (Soft blue)
        anatomy = data.get("anatomy", "")
        if anatomy:
            anat_font = QFont(option.font)
            anat_font.setPointSize(9)
            anat_font.setBold(True)
            painter.setFont(anat_font)
            painter.setPen(QColor("#38bdf8") if is_selected else QColor("#0284c7"))
            anat_rect = QRect(rect.left() + 14, rect.top() + 46, rect.width() - 24, 16)
            painter.drawText(anat_rect, Qt.AlignLeft | Qt.AlignVCenter, anatomy)

        painter.restore()


class ScaledImageLabel(QLabel):
    """
    High-performance QLabel that smoothly scales pixmaps with debounced resizing
    and cached display resolution to avoid freezing the UI thread.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #050508; border: 1px solid #1a1d26; border-radius: 8px;")
        self.original_pixmap = None
        self._last_scaled_size = QSize(0, 0)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)  # 40ms debounce for silky smooth resizing
        self._resize_timer.timeout.connect(self._do_scale)

    def set_pixmap(self, pixmap):
        self.original_pixmap = pixmap
        self._last_scaled_size = QSize(0, 0)
        self._do_scale()

    def _do_scale(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            w = max(50, self.width() - 8)
            h = max(50, self.height() - 8)
            current_target = QSize(w, h)
            if self._last_scaled_size == current_target:
                return
            scaled = self.original_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._last_scaled_size = current_target
            self.clear()
            super().setPixmap(scaled)
        else:
            self.clear()
            self.setText("No film selected")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()


class EditReviewDialog(QDialog):
    """
    Surgeon Findings & Notes Editor Modal:
    Allows adjusting implant counts, radiographic facts, and clinical remarks.
    """
    def __init__(self, patient_data, parent=None):
        super().__init__(parent)
        self.patient_data = patient_data
        self.setWindowTitle(f"Edit Findings & Clinical Remarks — {patient_data.get('name', 'Patient')}")
        self.setMinimumWidth(580)
        self.resize(600, 620)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e21;
                color: #dedee2;
            }
            QLabel {
                color: #d1d5db;
                font-size: 12px;
            }
            QLabel#dialogTitle {
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #9ca3af;
                font-size: 11px;
            }
            QLabel#fieldLabel {
                color: #93c5fd;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QTextEdit {
                background-color: #171719;
                border: 1px solid #33333b;
                border-radius: 5px;
                padding: 8px;
                color: #ffffff;
                font-size: 12px;
                line-height: 1.4;
            }
            QTextEdit:focus {
                border: 1px solid #2563eb;
                background-color: #1b1b22;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header banner
        header = QVBoxLayout()
        header.setSpacing(3)
        lbl_title = QLabel(f"Edit Findings & Clinical Remarks: {patient_data.get('name', 'Patient')}")
        lbl_title.setObjectName("dialogTitle")
        header.addWidget(lbl_title)

        info_sub = f"ID: {patient_data.get('hospital_id', '—')}  ·  {patient_data.get('age_sex', '—')}  ·  {patient_data.get('film_count', 0)} Films  ·  {patient_data.get('anatomy_views', '').split('(')[0].strip()}"
        lbl_sub = QLabel(info_sub)
        lbl_sub.setObjectName("dialogSubtitle")
        header.addWidget(lbl_sub)
        layout.addLayout(header)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #2e2e36;")
        layout.addWidget(div)

        # Section 1: Hardware & Implants
        lbl_hw = QLabel("ORTHOPEDIC HARDWARE & IMPLANTS (EDIT COUNTS / SPECS)")
        lbl_hw.setObjectName("fieldLabel")
        layout.addWidget(lbl_hw)

        self.txt_hardware = QTextEdit()
        self.txt_hardware.setPlaceholderText("e.g. 7-hole distal fibular locking plate, 5 bicortical screws, 1 lag screw")
        self.txt_hardware.setPlainText(patient_data.get('hardware', ''))
        self.txt_hardware.setFixedHeight(75)
        layout.addWidget(self.txt_hardware)

        # Section 2: Radiographic Facts & Alignment
        lbl_facts = QLabel("RADIOGRAPHIC FACTS & ANATOMICAL ALIGNMENT")
        lbl_facts.setObjectName("fieldLabel")
        layout.addWidget(lbl_facts)

        self.txt_facts = QTextEdit()
        self.txt_facts.setPlaceholderText("Radiographic alignment, joint mortise congruity, cortical step-offs...")
        self.txt_facts.setPlainText(patient_data.get('facts', ''))
        self.txt_facts.setFixedHeight(95)
        layout.addWidget(self.txt_facts)

        # Section 3: Surgeon Clinical Remarks / Action Plan
        lbl_notes = QLabel("SURGEON CLINICAL REMARKS & ACTION PLAN")
        lbl_notes.setObjectName("fieldLabel")
        layout.addWidget(lbl_notes)

        self.txt_notes = QTextEdit()
        self.txt_notes.setPlaceholderText("e.g. Plan hardware removal in 6 weeks. Non-weight bearing 2 more weeks, follow-up AP/LAT.")
        self.txt_notes.setPlainText(patient_data.get('surgeon_notes', ''))
        self.txt_notes.setFixedHeight(85)
        layout.addWidget(self.txt_notes)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_reset = QPushButton("Reset to AI Findings")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setToolTip("Discard manual edits and restore original AI-extracted hardware and facts")
        self.btn_reset.setStyleSheet("background-color: #27272e; color: #a1a1aa; border: 1px solid #373740; font-size: 11px;")
        self.btn_reset.clicked.connect(self.reset_to_ai)
        btn_bar.addWidget(self.btn_reset)

        btn_bar.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save and Apply")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet("background-color: #166534; color: #ffffff; border: 1px solid #22c55e; font-weight: 600; padding: 6px 16px;")
        self.btn_save.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_save)

        layout.addLayout(btn_bar)

    def reset_to_ai(self):
        ai_hw = self.patient_data.get('ai_hardware', '')
        ai_facts = self.patient_data.get('ai_facts', '')
        self.txt_hardware.setPlainText(ai_hw)
        self.txt_facts.setPlainText(ai_facts)

    def get_values(self):
        return {
            "hardware": self.txt_hardware.toPlainText().strip(),
            "facts": self.txt_facts.toPlainText().strip(),
            "surgeon_notes": self.txt_notes.toPlainText().strip(),
        }


class QueueManagerDialog(QDialog):
    """
    Workstation Ingestion Queue Manager Modal:
    Provides live oversight and control of large batch background ingestion (e.g. 50 patient folders).
    Allows pausing, resuming, clearing remaining queue, enqueuing more folders, and seeing throughput.
    """
    def __init__(self, queue_worker, parent=None):
        super().__init__(parent)
        self.worker = queue_worker
        self.setWindowTitle("Background Ingestion Queue Manager")
        self.resize(720, 580)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
            }
            QLabel {
                color: #d1d5db;
                font-size: 12px;
            }
            QLabel#mgrTitle {
                color: #ffffff;
                font-size: 16px;
                font-weight: 700;
            }
            QTableWidget {
                background-color: #121215;
                gridline-color: #27272a;
                border: 1px solid #2d2d33;
                border-radius: 6px;
                color: #e4e4e7;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #1e1e24;
                color: #9ca3af;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #33333b;
                font-weight: 600;
                font-size: 11px;
            }
            QProgressBar {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                text-align: center;
                color: #ffffff;
                font-weight: 600;
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
                border-radius: 4px;
            }
            QPushButton {
                background-color: #27272a;
                color: #ffffff;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3f3f46;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header with title and status badge
        header_row = QHBoxLayout()
        lbl_title = QLabel("⚡ Background Ingestion Queue")
        lbl_title.setObjectName("mgrTitle")
        header_row.addWidget(lbl_title)
        header_row.addStretch()

        self.lbl_status_pill = QLabel("Idle")
        self.lbl_status_pill.setStyleSheet(
            "background-color: #27272a; color: #a1a1aa; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px 10px; font-weight: 600; font-size: 11px;"
        )
        header_row.addWidget(self.lbl_status_pill)
        layout.addLayout(header_row)

        # Stats Cards Grid
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        def make_metric_card(title, initial_val="0"):
            card = QFrame()
            card.setStyleSheet("background-color: #1f1f23; border: 1px solid #2d2d35; border-radius: 6px; padding: 6px 10px;")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(0, 0, 0, 0)
            c_lay.setSpacing(2)
            lbl_t = QLabel(title.upper())
            lbl_t.setStyleSheet("color: #71717a; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;")
            lbl_v = QLabel(initial_val)
            lbl_v.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 700;")
            c_lay.addWidget(lbl_t)
            c_lay.addWidget(lbl_v)
            return card, lbl_v

        card_comp, self.val_completed = make_metric_card("Completed Cases")
        card_pend, self.val_pending = make_metric_card("Pending in Queue")
        card_xrays, self.val_xrays = make_metric_card("Total Radiographs")
        card_rate, self.val_rate = make_metric_card("Ingestion Speed", "—")

        stats_row.addWidget(card_comp)
        stats_row.addWidget(card_pend)
        stats_row.addWidget(card_xrays)
        stats_row.addWidget(card_rate)
        layout.addLayout(stats_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Active Folder Box
        self.active_box = QFrame()
        self.active_box.setStyleSheet("background-color: #171d2c; border: 1px solid #1e3a8a; border-radius: 6px; padding: 8px 12px;")
        ab_lay = QHBoxLayout(self.active_box)
        ab_lay.setContentsMargins(0, 0, 0, 0)
        ab_lay.setSpacing(8)
        self.lbl_active_folder = QLabel("Current Task: Ingestion queue is idle.")
        self.lbl_active_folder.setStyleSheet("color: #93c5fd; font-size: 12px; font-weight: 500;")
        ab_lay.addWidget(self.lbl_active_folder)
        layout.addWidget(self.active_box)

        # Queue Table
        lbl_tbl = QLabel("QUEUED & RECENTLY PROCESSED PATIENT FOLDERS")
        lbl_tbl.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
        layout.addWidget(lbl_tbl)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Folder / Case", "Status", "Films", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 65)
        self.table.setColumnWidth(3, 160)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table, stretch=1)

        # Control Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_pause = QPushButton("Pause Ingestion")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.clicked.connect(self.on_toggle_pause)
        btn_bar.addWidget(self.btn_pause)

        self.btn_clear = QPushButton("Cancel Pending Queue")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.setStyleSheet("background-color: #3b1d1d; color: #fca5a5; border: 1px solid #7f1d1d;")
        self.btn_clear.clicked.connect(self.on_clear_queue)
        btn_bar.addWidget(self.btn_clear)

        self.btn_add = QPushButton("+ Enqueue More Folders...")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.on_add_folders)
        btn_bar.addWidget(self.btn_add)

        btn_bar.addStretch()

        self.btn_close = QPushButton("Done (Keep Running in Background)")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("background-color: #22c55e; color: #000000; font-weight: 600; padding: 6px 16px;")
        self.btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_close)

        layout.addLayout(btn_bar)

        # Connect live updates from worker
        self.worker.queue_state_changed.connect(self.update_ui)
        self.update_ui(self.worker.get_status())

    def update_ui(self, status):
        pending = status.get('pending_count', 0)
        completed = status.get('completed_count', 0)
        total = status.get('total_count', 0)
        is_running = status.get('is_running', False)
        is_paused = status.get('is_paused', False)
        total_xrays = status.get('total_xrays', 0)
        cur_folder = status.get('current_folder')
        cur_film = status.get('current_film')
        rate = status.get('avg_film_sec', 0.0)

        self.val_completed.setText(str(completed))
        self.val_pending.setText(str(pending))
        self.val_xrays.setText(str(total_xrays))
        self.val_rate.setText(f"{rate}s / film" if rate > 0 else "—")

        pct = int((completed / max(1, total)) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{pct}% ({completed}/{total} studies completed)")

        if is_paused:
            self.lbl_status_pill.setText("⏸ Paused")
            self.lbl_status_pill.setStyleSheet("background-color: #422006; color: #fde047; border: 1px solid #a16207; border-radius: 4px; padding: 4px 10px; font-weight: 600;")
            self.btn_pause.setText("Resume Ingestion")
            self.lbl_active_folder.setText(f"Ingestion paused by surgeon. {pending} studies waiting in queue.")
        elif is_running:
            self.lbl_status_pill.setText("⚡ Ingesting")
            self.lbl_status_pill.setStyleSheet("background-color: #172554; color: #93c5fd; border: 1px solid #2563eb; border-radius: 4px; padding: 4px 10px; font-weight: 600;")
            self.btn_pause.setText("Pause Ingestion")
            film_txt = f" · Film: {cur_film}" if cur_film else ""
            self.lbl_active_folder.setText(f"Active Case: {cur_folder or 'Analyzing'}{film_txt} (Total: {completed + 1}/{total})")
        else:
            self.lbl_status_pill.setText("Idle" if total == 0 else "✓ Finished")
            bg = "#14532d" if total > 0 else "#27272a"
            fg = "#86efac" if total > 0 else "#a1a1aa"
            self.lbl_status_pill.setStyleSheet(f"background-color: {bg}; color: {fg}; border-radius: 4px; padding: 4px 10px; font-weight: 600;")
            self.btn_pause.setText("Pause Ingestion")
            if total > 0:
                self.lbl_active_folder.setText(f"Queue Complete: Ingested {completed} patient studies ({total_xrays} films).")
            else:
                self.lbl_active_folder.setText("Queue is idle. Drop or choose patient folders anytime.")

        # Re-populate queue table
        self.table.setRowCount(0)
        row = 0

        # 1. Currently active
        if cur_folder and is_running:
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"▶ {cur_folder}"))
            it_status = QTableWidgetItem("Ingesting")
            it_status.setForeground(QColor("#38bdf8"))
            self.table.setItem(row, 1, it_status)
            self.table.setItem(row, 2, QTableWidgetItem("Active"))
            self.table.setItem(row, 3, QTableWidgetItem(cur_film or "Analyzing X-rays..."))
            row += 1

        # 2. Pending folders
        pending_list = status.get('pending_folders', [])
        for p_name in pending_list[:40]:
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(p_name))
            it_status = QTableWidgetItem("Pending")
            it_status.setForeground(QColor("#a1a1aa"))
            self.table.setItem(row, 1, it_status)
            self.table.setItem(row, 2, QTableWidgetItem("—"))
            self.table.setItem(row, 3, QTableWidgetItem("Waiting in queue"))
            row += 1

        # 3. Completed history
        history = status.get('history', [])
        for item in reversed(history[:20]):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(item.get('name') or item.get('folder', 'Case')))
            it_status = QTableWidgetItem("✓ Ready")
            it_status.setForeground(QColor("#4ade80"))
            self.table.setItem(row, 1, it_status)
            self.table.setItem(row, 2, QTableWidgetItem(str(item.get('films', 0))))
            dur = item.get('duration_sec', 0.0)
            self.table.setItem(row, 3, QTableWidgetItem(f"Done in {dur}s"))
            row += 1

    def on_toggle_pause(self):
        self.worker.toggle_pause()

    def on_clear_queue(self):
        cleared = self.worker.clear_queue()
        self.lbl_active_folder.setText(f"Removed {cleared} pending folders from queue.")

    def on_add_folders(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Patient Folder or Batch Directory to Enqueue")
        if folder:
            self.worker.enqueue_folders(folder)


class ImportPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(WORKSTATION_STYLE)
        self.setAcceptDrops(True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # 1. Top Controls Bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.btn_choose = QPushButton("+ Ingest Folder")
        self.btn_choose.setCursor(Qt.PointingHandCursor)
        self.btn_choose.setToolTip("Select a single patient folder or image directory to enqueue")
        self.btn_choose.clicked.connect(self.choose_folder)
        top_bar.addWidget(self.btn_choose)

        self.btn_batch = QPushButton("+ Ingest Batch")
        self.btn_batch.setCursor(Qt.PointingHandCursor)
        self.btn_batch.setToolTip("Select a root directory containing multiple patient folders (e.g. 50 patient batch)")
        self.btn_batch.clicked.connect(self.choose_batch)
        top_bar.addWidget(self.btn_batch)

        self.btn_manage_queue = QPushButton("● Queue: Idle")
        self.btn_manage_queue.setCursor(Qt.PointingHandCursor)
        self.btn_manage_queue.setToolTip("Open Background Queue Manager to inspect pending studies, pause, or clear queue")
        self.btn_manage_queue.setStyleSheet(
            "background-color: #12141c; color: #64748b; border: 1px solid #1e2230; border-radius: 6px; padding: 5px 12px; font-size: 11px;"
        )
        self.btn_manage_queue.clicked.connect(self.open_queue_manager)
        top_bar.addWidget(self.btn_manage_queue)
        self.lbl_queue_pill = self.btn_manage_queue

        self.btn_pause_queue = QPushButton("Pause")
        self.btn_pause_queue.setCursor(Qt.PointingHandCursor)
        self.btn_pause_queue.setStyleSheet("padding: 5px 10px; font-size: 11px; background-color: #181b26; border: 1px solid #232838; border-radius: 5px;")
        self.btn_pause_queue.setVisible(False)
        self.btn_pause_queue.clicked.connect(self.toggle_queue_pause)
        top_bar.addWidget(self.btn_pause_queue)

        # Search filter
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search patients, anatomy, hardware...")
        self.search_input.setMaximumWidth(260)
        self.search_input.textChanged.connect(self.filter_patients)
        top_bar.addWidget(self.search_input)

        top_bar.addStretch()

        # View mode segmented pill container (single cohesive control instead of separated boxes)
        view_pill = QFrame()
        view_pill.setObjectName("viewPill")
        view_pill.setStyleSheet("QFrame#viewPill { background-color: #12141c; border: 1px solid #1e2230; border-radius: 6px; padding: 2px; }")
        view_pill_lay = QHBoxLayout(view_pill)
        view_pill_lay.setContentsMargins(2, 2, 2, 2)
        view_pill_lay.setSpacing(2)

        self.btn_view_study = QPushButton("Study Viewer")
        self.btn_view_study.setObjectName("tabBtn")
        self.btn_view_study.setCheckable(True)
        self.btn_view_study.setChecked(True)
        self.btn_view_study.setCursor(Qt.PointingHandCursor)

        self.btn_view_table = QPushButton("Summary Table")
        self.btn_view_table.setObjectName("tabBtn")
        self.btn_view_table.setCheckable(True)
        self.btn_view_table.setCursor(Qt.PointingHandCursor)

        self.tab_group = QButtonGroup(self)
        self.tab_group.addButton(self.btn_view_study)
        self.tab_group.addButton(self.btn_view_table)
        self.btn_view_study.clicked.connect(lambda: self.switch_view(0))
        self.btn_view_table.clicked.connect(lambda: self.switch_view(1))

        view_pill_lay.addWidget(self.btn_view_study)
        view_pill_lay.addWidget(self.btn_view_table)
        top_bar.addWidget(view_pill)

        self.btn_export_excel = QPushButton("📊 Download Excel Sheet")
        self.btn_export_excel.setCursor(Qt.PointingHandCursor)
        self.btn_export_excel.setToolTip("Export patient records to an Excel spreadsheet with clickable folder hyperlinks for all patient names")
        self.btn_export_excel.setStyleSheet(
            "background-color: #064e3b; color: #6ee7b7; border: 1px solid #059669; border-radius: 6px; padding: 5px 13px; font-weight: 600;"
        )
        self.btn_export_excel.clicked.connect(self.export_to_excel)
        top_bar.addWidget(self.btn_export_excel)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet("color: #64748b; font-size: 12px; font-weight: 500; margin-left: 8px;")
        top_bar.addWidget(self.lbl_stats)

        main_layout.addLayout(top_bar)

        # Visual Drag & Drop feedback banner
        self.lbl_drop_banner = QLabel("📂 Drop patient folders or batch directory anywhere to enqueue into background ingestion")
        self.lbl_drop_banner.setAlignment(Qt.AlignCenter)
        self.lbl_drop_banner.setStyleSheet(
            "background-color: #172554; color: #93c5fd; border: 2px dashed #3b82f6; border-radius: 6px; padding: 7px; font-weight: 600; font-size: 12px;"
        )
        self.lbl_drop_banner.setVisible(False)
        main_layout.addWidget(self.lbl_drop_banner)

        # Progress bar (only visible during analysis)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # 2. Main Stack (Page 0: Study Viewer, Page 1: Summary Table)
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, stretch=1)

        # --- PAGE 0: STUDY VIEWER ---
        page_study = QWidget()
        page_study_layout = QHBoxLayout(page_study)
        page_study_layout.setContentsMargins(0, 0, 0, 0)
        page_study_layout.setSpacing(10)

        splitter_main = QSplitter(Qt.Horizontal)
        splitter_main.setHandleWidth(4)

        # Left Column: Patient Worklist
        left_col = QWidget()
        left_col.setMinimumWidth(280)
        left_col.setMaximumWidth(380)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        lbl_patients = QLabel("PATIENT CASES")
        lbl_patients.setObjectName("sectionTitle")
        left_layout.addWidget(lbl_patients)

        self.patient_list = QListWidget()
        self.patient_list.setObjectName("patientList")
        self.patient_list.setMouseTracking(True)
        self.patient_list.setCursor(Qt.PointingHandCursor)
        self.patient_delegate = PatientCardDelegate(self.patient_list)
        self.patient_list.setItemDelegate(self.patient_delegate)

        # Connect BOTH currentRowChanged AND itemClicked for 100% reliable click registration
        self.patient_list.currentRowChanged.connect(self.on_patient_row_changed)
        self.patient_list.itemClicked.connect(self.on_patient_item_clicked)
        self.patient_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.patient_list.customContextMenuRequested.connect(self.show_patient_context_menu)
        left_layout.addWidget(self.patient_list)

        splitter_main.addWidget(left_col)
        splitter_main.setCollapsible(0, False)

        # Right Column: Study Workspace (Header + Viewport + Findings)
        right_workspace = QWidget()
        workspace_layout = QVBoxLayout(right_workspace)
        workspace_layout.setContentsMargins(4, 0, 0, 0)
        workspace_layout.setSpacing(8)

        # Header bar (integrated top surface, not a floating boxed card)
        header_card = QFrame()
        header_card.setObjectName("headerCard")
        header_card.setStyleSheet("QFrame#headerCard { background-color: #12141c; border: 1px solid #1e2230; border-radius: 8px; } QLabel { border: none; background: transparent; }")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(14, 8, 14, 8)
        header_layout.setSpacing(12)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        self.lbl_patient_name = QLabel("Select a patient")
        self.lbl_patient_name.setStyleSheet("font-size: 16px; font-weight: 700; color: #ffffff;")
        name_col.addWidget(self.lbl_patient_name)

        self.lbl_patient_meta = QLabel("No patient selected")
        self.lbl_patient_meta.setStyleSheet("font-size: 12px; color: #94a3b8; font-weight: 500;")
        name_col.addWidget(self.lbl_patient_meta)
        header_layout.addLayout(name_col)

        # Backwards compatibility dummy attributes (hidden)
        self.badge_age_sex = QLabel("")
        self.badge_id = QLabel("")
        self.badge_films = QLabel("")
        self.badge_age_sex.setVisible(False)
        self.badge_id.setVisible(False)
        self.badge_films.setVisible(False)
        header_layout.addWidget(self.badge_age_sex)
        header_layout.addWidget(self.badge_id)
        header_layout.addWidget(self.badge_films)

        header_layout.addStretch()

        self.btn_open_folder = QPushButton("📁 Open Patient Folder")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setToolTip("Open this patient's directory in Finder / File Explorer")
        self.btn_open_folder.setStyleSheet(
            "background-color: #181b26; color: #cbd5e1; border: 1px solid #282d3e; border-radius: 6px; padding: 6px 13px; font-size: 12px; font-weight: 500;"
        )
        self.btn_open_folder.clicked.connect(self.open_current_patient_folder)
        header_layout.addWidget(self.btn_open_folder)

        workspace_layout.addWidget(header_card)

        # Inner Splitter (Center: Film Canvas, Right: Findings)
        inner_splitter = QSplitter(Qt.Horizontal)
        inner_splitter.setHandleWidth(4)

        # Film Canvas Area
        canvas_widget = QWidget()
        canvas_layout = QVBoxLayout(canvas_widget)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(6)

        # Projections segmented bar inside horizontal scroll area
        self.film_scroll = QScrollArea()
        self.film_scroll.setWidgetResizable(True)
        self.film_scroll.setFixedHeight(40)
        self.film_scroll.setFrameShape(QFrame.NoFrame)
        self.film_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.film_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.film_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:horizontal { height: 4px; background: #0c0d12; border-radius: 2px; }
            QScrollBar::handle:horizontal { background: #282d3e; border-radius: 2px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
        """)

        self.film_container = QWidget()
        self.film_container.setObjectName("filmContainer")
        self.film_container.setStyleSheet("QWidget#filmContainer { background-color: #12141c; border: 1px solid #1e2230; border-radius: 6px; }")
        self.pills_bar = QHBoxLayout(self.film_container)
        self.pills_bar.setSizeConstraint(QHBoxLayout.SetMinAndMaxSize)
        self.pills_bar.setContentsMargins(4, 3, 4, 3)
        self.pills_bar.setSpacing(4)
        self.film_scroll.setWidget(self.film_container)

        canvas_layout.addWidget(self.film_scroll)

        self.image_canvas = ScaledImageLabel()
        canvas_layout.addWidget(self.image_canvas, stretch=1)

        self.lbl_film_info = QLabel("")
        self.lbl_film_info.setAlignment(Qt.AlignCenter)
        self.lbl_film_info.setStyleSheet("color: #64748b; font-size: 11px;")
        canvas_layout.addWidget(self.lbl_film_info)

        inner_splitter.addWidget(canvas_widget)
        inner_splitter.setCollapsible(0, False)

        # Right Panel: Orthopedic Findings & Hardware (Unified Inspector)
        findings_widget = QWidget()
        findings_widget.setObjectName("findingsWidget")
        findings_widget.setStyleSheet(
            "QWidget#findingsWidget { background-color: #12141c; border: 1px solid #1e2230; border-radius: 8px; } QLabel { border: none; background: transparent; }"
        )
        findings_layout = QVBoxLayout(findings_widget)
        findings_layout.setContentsMargins(14, 14, 14, 14)
        findings_layout.setSpacing(10)

        # 1. Inspector Header
        findings_header = QHBoxLayout()
        findings_header.setContentsMargins(0, 0, 0, 2)
        lbl_findings_title = QLabel("CLINICAL ASSESSMENT")
        lbl_findings_title.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; letter-spacing: 0.8px;")
        findings_header.addWidget(lbl_findings_title)
        findings_header.addStretch()

        self.btn_edit_findings = QPushButton("✎ Edit Findings")
        self.btn_edit_findings.setCursor(Qt.PointingHandCursor)
        self.btn_edit_findings.setStyleSheet(
            "background-color: #1e293b; color: #93c5fd; border: 1px solid #3b82f6; font-size: 11px; padding: 4px 10px; font-weight: 600; border-radius: 5px;"
        )
        self.btn_edit_findings.clicked.connect(lambda: self.open_edit_review_dialog())
        findings_header.addWidget(self.btn_edit_findings)
        findings_layout.addLayout(findings_header)

        # 2. Hardware Inventory Section (clean typography, no box)
        self.lbl_hw_title = QLabel("ORTHOPEDIC HARDWARE & IMPLANTS")
        self.lbl_hw_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; margin-top: 4px;")
        findings_layout.addWidget(self.lbl_hw_title)

        self.txt_hardware = QTextEdit()
        self.txt_hardware.setReadOnly(True)
        self.txt_hardware.setStyleSheet(
            "background-color: #0d0e14; border: 1px solid #1a1d28; border-radius: 6px; padding: 8px; color: #f1f5f9; font-size: 12px; line-height: 1.45;"
        )
        self.txt_hardware.setFixedHeight(85)
        findings_layout.addWidget(self.txt_hardware)

        # 3. Objective Facts & Alignment Section (clean typography, no box)
        lbl_facts_title = QLabel("ALIGNMENT & RADIOGRAPHIC FINDINGS")
        lbl_facts_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; margin-top: 4px;")
        findings_layout.addWidget(lbl_facts_title)

        self.txt_facts = QTextEdit()
        self.txt_facts.setReadOnly(True)
        self.txt_facts.setStyleSheet(
            "background-color: #0d0e14; border: 1px solid #1a1d28; border-radius: 6px; padding: 8px; color: #cbd5e1; font-size: 12px; line-height: 1.45;"
        )
        findings_layout.addWidget(self.txt_facts, stretch=1)

        # 4. Surgeon Clinical Remarks (Special distinct shaded callout!)
        self.card_notes = QFrame()
        self.card_notes.setObjectName("cardNotes")
        self.card_notes.setStyleSheet(
            "QFrame#cardNotes { background-color: #171d29; border: 1px solid #1e3a5f; border-left: 4px solid #38bdf8; border-radius: 6px; } QLabel { border: none; background: transparent; }"
        )
        card_notes_layout = QVBoxLayout(self.card_notes)
        card_notes_layout.setContentsMargins(6, 6, 6, 6)
        card_notes_layout.setSpacing(4)

        notes_header = QHBoxLayout()
        lbl_notes_title = QLabel("SURGEON CLINICAL REMARKS")
        lbl_notes_title.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 700; letter-spacing: 0.6px;")
        notes_header.addWidget(lbl_notes_title)
        notes_header.addStretch()

        self.lbl_reviewed_time = QLabel("")
        self.lbl_reviewed_time.setStyleSheet("color: #64748b; font-size: 10px;")
        notes_header.addWidget(self.lbl_reviewed_time)
        card_notes_layout.addLayout(notes_header)

        self.lbl_surgeon_notes = QLabel("No clinical remarks recorded.")
        self.lbl_surgeon_notes.setWordWrap(True)
        self.lbl_surgeon_notes.setStyleSheet("color: #f1f5f9; font-size: 12px;")
        card_notes_layout.addWidget(self.lbl_surgeon_notes)
        findings_layout.addWidget(self.card_notes)

        # 5. Active Film Metadata & Reveal in Finder
        film_meta_row = QHBoxLayout()
        film_meta_row.setContentsMargins(0, 4, 0, 0)
        self.lbl_active_film_meta = QLabel("Select a projection")
        self.lbl_active_film_meta.setStyleSheet("color: #64748b; font-size: 11px;")
        film_meta_row.addWidget(self.lbl_active_film_meta, stretch=1)

        self.btn_reveal_film = QPushButton("Show in Finder ↗")
        self.btn_reveal_film.setCursor(Qt.PointingHandCursor)
        self.btn_reveal_film.setStyleSheet(
            "font-size: 11px; padding: 5px 10px; background-color: #181b26; border: 1px solid #232838; border-radius: 5px; color: #cbd5e1;"
        )
        self.btn_reveal_film.clicked.connect(self.reveal_active_film)
        self.btn_reveal_film.setEnabled(False)
        film_meta_row.addWidget(self.btn_reveal_film)
        findings_layout.addLayout(film_meta_row)

        inner_splitter.addWidget(findings_widget)
        inner_splitter.setCollapsible(1, False)
        inner_splitter.setStretchFactor(0, 3)
        inner_splitter.setStretchFactor(1, 2)
        inner_splitter.setSizes([560, 360])

        workspace_layout.addWidget(inner_splitter, stretch=1)
        splitter_main.addWidget(right_workspace)

        splitter_main.setStretchFactor(0, 1)
        splitter_main.setStretchFactor(1, 4)
        splitter_main.setSizes([300, 960])

        page_study_layout.addWidget(splitter_main)
        self.stack.addWidget(page_study)

        # --- PAGE 1: SUMMARY TABLE ---
        page_table = QWidget()
        page_table_layout = QVBoxLayout(page_table)
        page_table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Patient Name", "Age/Sex", "Hospital ID", "Films",
            "Anatomy", "Hardware Summary", "Surgeon Remarks", "Radiographic Facts"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setCursor(Qt.PointingHandCursor)

        header_view = self.table.horizontalHeader()
        for c in range(7):
            header_view.setSectionResizeMode(c, QHeaderView.Interactive)
        header_view.setSectionResizeMode(7, QHeaderView.Stretch)

        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 65)
        self.table.setColumnWidth(2, 85)
        self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 200)
        self.table.setColumnWidth(6, 210)

        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        page_table_layout.addWidget(self.table)
        self.stack.addWidget(page_table)

        # State & Caches
        self.patient_summaries = []
        self.visible_patients = []
        self.film_group = None
        self._pixmap_cache = {}  # In-memory pixmap cache: path -> QPixmap
        self._current_selected_row = -1

        # Background Ingestion Queue Worker
        self.queue_worker = IngestionQueueWorker(parent=self)
        self.queue_worker.queue_updated.connect(self.on_queue_updated)
        self.queue_worker.progress.connect(self.on_queue_progress)
        self.queue_worker.patient_ingested.connect(self.on_patient_ingested)
        self.queue_worker.all_completed.connect(self.on_queue_all_completed)
        self.queue_worker.failed.connect(self.on_queue_failed)
        self.queue_worker.queue_state_changed.connect(self.on_queue_state_changed)

        # Initial load
        self.load_data()

    def switch_view(self, index):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.btn_view_study.setChecked(True)
        else:
            self.btn_view_table.setChecked(True)

    def load_data(self, preserve_selection_id=None, silent_refresh=False):
        try:
            if preserve_selection_id is None and 0 <= self._current_selected_row < len(self.visible_patients):
                preserve_selection_id = self.visible_patients[self._current_selected_row]['patient_id']

            # 1. Save scroll positions
            v_scroll = self.patient_list.verticalScrollBar().value()
            tbl_vscroll = self.table.verticalScrollBar().value()
            tbl_hscroll = self.table.horizontalScrollBar().value()

            conn = connect()
            self.patient_summaries = get_patients_summary(conn)
            conn.close()

            q = self.search_input.text().strip().lower()
            if not q:
                self.visible_patients = list(self.patient_summaries)
            else:
                self.visible_patients = [
                    p for p in self.patient_summaries
                    if q in p['name'].lower()
                    or q in str(p['hospital_id']).lower()
                    or q in p.get('anatomy_views', '').lower()
                    or q in p.get('hardware', '').lower()
                    or q in p.get('facts', '').lower()
                    or q in p.get('surgeon_notes', '').lower()
                ]

            target_row = 0
            if preserve_selection_id is not None:
                for idx, p in enumerate(self.visible_patients):
                    if p['patient_id'] == preserve_selection_id:
                        target_row = idx
                        break

            # 2. Render patient list with signals blocked so currentRowChanged doesn't fire
            self.patient_list.blockSignals(True)
            self.render_patient_list()
            if self.visible_patients:
                self.patient_list.setCurrentRow(target_row)
            self.patient_list.verticalScrollBar().setValue(v_scroll)
            self.patient_list.blockSignals(False)

            # 3. Render summary table with signals blocked
            self.table.blockSignals(True)
            cur_tbl_row = self.table.currentRow()
            self.render_table()
            if 0 <= cur_tbl_row < self.table.rowCount():
                self.table.setCurrentCell(cur_tbl_row, 0)
            self.table.verticalScrollBar().setValue(tbl_vscroll)
            self.table.horizontalScrollBar().setValue(tbl_hscroll)
            self.table.blockSignals(False)

            # 4. Update stats
            total_films = sum(p['film_count'] for p in self.patient_summaries)
            self.lbl_stats.setText(f"{len(self.patient_summaries)} patients ({total_films} films)")

            # 5. ZERO INTERRUPTION:
            # If silent_refresh is True, do NOT call select_patient_by_index!
            # The active patient, active film, canvas zoom, and pills stay 100% untouched!
            if not silent_refresh:
                if self.visible_patients:
                    self.select_patient_by_index(target_row)
            else:
                self._current_selected_row = target_row
                if 0 <= target_row < len(self.visible_patients):
                    p = self.visible_patients[target_row]
                    films = p.get('films', [])
                    if films and Path(films[0]['file_path']).exists():
                        self.current_patient_folder = Path(films[0]['file_path']).parent
        except Exception as e:
            print(f"Error loading records: {e}")

    def render_patient_list(self):
        self.patient_list.clear()
        for p in self.visible_patients:
            item = QListWidgetItem()
            anatomy = p.get('anatomy_views', '').split('(')[0].strip()
            data_payload = {
                "name": p['name'],
                "age_sex": p['age_sex'],
                "hospital_id": str(p['hospital_id']),
                "film_count": p['film_count'],
                "anatomy": anatomy,
                "raw": p
            }
            item.setData(Qt.UserRole, data_payload)
            item.setToolTip(f"{p['name']} ({p['age_sex']}) - ID: {p['hospital_id']}")
            self.patient_list.addItem(item)

    def render_table(self):
        self.table.setRowCount(0)
        for p in self.visible_patients:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(p['name']))

            item_age = QTableWidgetItem(p['age_sex'])
            item_age.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, item_age)

            item_id = QTableWidgetItem(str(p['hospital_id']))
            item_id.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_id)

            item_f = QTableWidgetItem(str(p['film_count']))
            item_f.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, item_f)

            anatomy = p.get('anatomy_views', '').split('(')[0].strip()
            self.table.setItem(row, 4, QTableWidgetItem(anatomy))

            hw_str = p['hardware']
            if p.get('is_edited'):
                hw_str += " [Edited]"
            hw_item = QTableWidgetItem(hw_str)
            hw_item.setToolTip(p['hardware'])
            self.table.setItem(row, 5, hw_item)

            notes_item = QTableWidgetItem(p.get('surgeon_notes', ''))
            notes_item.setToolTip(p.get('surgeon_notes', ''))
            self.table.setItem(row, 6, notes_item)

            facts_item = QTableWidgetItem(p['facts'])
            facts_item.setToolTip(p['facts'])
            self.table.setItem(row, 7, facts_item)

    def filter_patients(self, query):
        q = query.strip().lower()
        if not q:
            self.visible_patients = list(self.patient_summaries)
        else:
            self.visible_patients = [
                p for p in self.patient_summaries
                if q in p['name'].lower()
                or q in str(p['hospital_id']).lower()
                or q in p.get('anatomy_views', '').lower()
                or q in p.get('hardware', '').lower()
                or q in p.get('facts', '').lower()
                or q in p.get('surgeon_notes', '').lower()
            ]
        self.render_patient_list()
        self.render_table()
        if self.visible_patients:
            self.patient_list.setCurrentRow(0)
            self.select_patient_by_index(0)

    def on_patient_row_changed(self, row):
        if row >= 0:
            self.select_patient_by_index(row)

    def on_patient_item_clicked(self, item):
        row = self.patient_list.row(item)
        if row >= 0:
            self.select_patient_by_index(row)

    def select_patient_by_index(self, index):
        if index < 0 or index >= len(self.visible_patients):
            return

        self._current_selected_row = index
        p = self.visible_patients[index]

        self.lbl_patient_name.setText(p['name'])
        meta_parts = []
        if p.get('age_sex'):
            meta_parts.append(p['age_sex'])
        if p.get('hospital_id'):
            meta_parts.append(f"Hospital ID: {p['hospital_id']}")
        meta_parts.append(f"{p.get('film_count', 0)} Films")
        self.lbl_patient_meta.setText("  ·  ".join(meta_parts))

        self.badge_age_sex.setText(f"Age/Sex: {p['age_sex']}")
        self.badge_id.setText(f"ID: {p['hospital_id']}")
        self.badge_films.setText(f"{p['film_count']} Films")

        # Hardware display
        hw = p['hardware']
        if p.get('is_edited'):
            self.lbl_hw_title.setText("ORTHOPEDIC HARDWARE & IMPLANTS (SURGEON EDITED)")
        else:
            self.lbl_hw_title.setText("ORTHOPEDIC HARDWARE & IMPLANTS (CROSS-PROJECTION RECONCILED)")

        hw_list = p.get('hardware_list')
        if not hw or hw.strip() in ("", "None", "[]", "No orthopaedic implants or surgical hardware identified."):
            self.txt_hardware.setPlainText("No orthopaedic implants or surgical hardware identified.")
        else:
            if hw_list and isinstance(hw_list, list):
                items = hw_list
            elif "\n" in hw:
                items = [h.strip() for h in hw.split("\n") if h.strip()]
            elif ";" in hw:
                items = [h.strip() for h in hw.split(";") if h.strip()]
            else:
                items = [h.strip() for h in re.split(r",\s*(?![^()]*\))", hw) if h.strip()]

            self.txt_hardware.setPlainText("\n".join(f"• {item}" for item in items))

        # Facts
        self.txt_facts.setPlainText(p['facts'])

        # Surgeon notes (distinct callout shade when remarks exist)
        notes = p.get('surgeon_notes', '').strip()
        if notes:
            self.lbl_surgeon_notes.setText(notes)
            self.lbl_surgeon_notes.setStyleSheet("color: #f1f5f9; font-size: 12px; line-height: 1.45; font-weight: 500;")
            self.card_notes.setStyleSheet(
                "QFrame#cardNotes { background-color: #171d29; border: 1px solid #1e3a5f; border-left: 4px solid #38bdf8; border-radius: 6px; } QLabel { border: none; background: transparent; }"
            )
        else:
            self.lbl_surgeon_notes.setText("No clinical remarks recorded. Click 'Edit Findings' above to add.")
            self.lbl_surgeon_notes.setStyleSheet("color: #64748b; font-size: 11px; font-style: italic;")
            self.card_notes.setStyleSheet(
                "QFrame#cardNotes { background-color: #10121a; border: 1px dashed #1e2230; border-radius: 6px; } QLabel { border: none; background: transparent; }"
            )

        reviewed_at = p.get('reviewed_at')
        if reviewed_at:
            self.lbl_reviewed_time.setText(f"Reviewed: {reviewed_at}")
        else:
            self.lbl_reviewed_time.setText("")

        # Track and enable opening current patient folder
        films = p.get('films', [])
        if films and Path(films[0]['file_path']).exists():
            self.current_patient_folder = Path(films[0]['file_path']).parent
            self.btn_open_folder.setEnabled(True)
            self.btn_open_folder.setToolTip(f"Open: {self.current_patient_folder}")
        else:
            self.current_patient_folder = None
            self.btn_open_folder.setEnabled(False)
            self.btn_open_folder.setToolTip("No folder found on disk for this patient")

        # Setup film selector buttons cleanly
        while self.pills_bar.count():
            child = self.pills_bar.takeAt(0)
            w = child.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        self.film_group = QButtonGroup(self)
        self.film_group.setExclusive(True)
        films = p.get('films', [])

        for idx, f in enumerate(films):
            part = (f['body_part'] or 'X-Ray').title()
            v_str = format_views(f['views'])
            btn_title = f"{idx+1}. {part}"
            if v_str:
                btn_title += f" ({v_str})"

            btn = QPushButton(btn_title)
            btn.setObjectName("filmBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setMinimumWidth(max(110, btn.sizeHint().width() + 18))
            self.film_group.addButton(btn, idx)
            self.pills_bar.addWidget(btn)

            btn.clicked.connect(
                lambda checked, f_data=f, title=btn_title: self.display_film(f_data, title)
            )

        if films:
            btn_first = self.film_group.button(0)
            if btn_first:
                btn_first.setChecked(True)
                f0 = films[0]
                v0 = format_views(f0['views'])
                title0 = f"1. {(f0['body_part'] or 'X-Ray').title()}" + (f" ({v0})" if v0 else "")
                self.display_film(f0, title0)

    def open_edit_review_dialog(self, patient_id=None):
        """Opens the surgeon review dialog to edit hardware counts, facts, and remarks."""
        if patient_id is None:
            if self._current_selected_row < 0 or self._current_selected_row >= len(self.visible_patients):
                return
            p = self.visible_patients[self._current_selected_row]
        else:
            p = next((x for x in self.patient_summaries if x['patient_id'] == patient_id), None)
            if not p:
                return

        pid = p['patient_id']
        dlg = EditReviewDialog(p, parent=self)
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.get_values()
            try:
                conn = connect()
                update_patient_review(
                    conn,
                    patient_id=pid,
                    surgeon_notes=vals["surgeon_notes"],
                    verified_hardware=vals["hardware"],
                    verified_facts=vals["facts"]
                )
                conn.close()
                self.load_data(preserve_selection_id=pid)
            except Exception as e:
                print(f"Error saving review edits: {e}")

    def export_to_excel(self):
        """
        Exports all patient studies to an Excel spreadsheet (.xlsx).
        The patient name in each row is a clickable hyperlink that opens
        the corresponding patient's folder directly on disk in Finder / File Explorer.
        """
        if not self.patient_summaries:
            QMessageBox.information(self, "No Records", "No patient records available to export.")
            return

        from datetime import datetime
        default_name = f"Orthopedic_Patient_Studies_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Patient Studies to Excel",
            str(Path.home() / "Downloads" / default_name),
            "Excel Files (*.xlsx)"
        )
        if not file_path:
            return

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Patient Studies"
            ws.views.sheetView[0].showGridLines = True

            # Headers
            headers = [
                "Patient Name", "Age/Sex", "Hospital ID", "Films",
                "Anatomy & Views", "Orthopedic Hardware & Implants",
                "Surgeon Clinical Remarks", "Radiographic Facts & Alignment",
                "Patient Folder Path"
            ]
            ws.append(headers)

            # Styling definitions
            header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

            thin_border = Border(
                left=Side(style='thin', color='CBD5E1'),
                right=Side(style='thin', color='CBD5E1'),
                top=Side(style='thin', color='CBD5E1'),
                bottom=Side(style='thin', color='CBD5E1')
            )

            # Format header row
            ws.row_dimensions[1].height = 28
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = header_align
                cell.border = thin_border

            # Data rows
            patients = self.patient_summaries
            alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

            for r_idx, p in enumerate(patients, start=2):
                films = p.get('films', [])
                folder_path = None
                if films:
                    cand = Path(films[0]['file_path']).parent
                    if cand.exists():
                        folder_path = cand.resolve()

                anatomy = p.get('anatomy_views', '').split('(')[0].strip()
                views = ", ".join(sorted(p.get('views', []))) if p.get('views') else "AP/LAT"
                anat_views = f"{anatomy} ({views})"

                hw_str = p.get('hardware', 'None')
                notes_str = p.get('surgeon_notes', '')
                facts_str = p.get('facts', '')
                folder_str = str(folder_path) if folder_path else "—"

                row_vals = [
                    p['name'],
                    p.get('age_sex', '—'),
                    str(p.get('hospital_id', '—')),
                    p.get('film_count', 0),
                    anat_views,
                    hw_str,
                    notes_str,
                    facts_str,
                    folder_str
                ]

                ws.append(row_vals)
                ws.row_dimensions[r_idx].height = 26
                use_fill = (r_idx % 2 == 1)

                for c_idx in range(1, len(row_vals) + 1):
                    cell = ws.cell(row=r_idx, column=c_idx)
                    cell.border = thin_border
                    if use_fill:
                        cell.fill = alt_fill

                    # Cell specific alignments & styles
                    if c_idx == 1:
                        # Patient Name with clickable hyperlink that opens folder
                        if folder_path:
                            file_uri = folder_path.as_uri()
                            cell.hyperlink = file_uri
                            cell.font = Font(name="Calibri", size=11, color="0563C1", underline="single", bold=True)
                        else:
                            cell.font = Font(name="Calibri", size=11, bold=True)
                        cell.alignment = Alignment(horizontal="left", vertical="center")
                    elif c_idx in (2, 3, 4):
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                        cell.font = Font(name="Calibri", size=10)
                    else:
                        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                        cell.font = Font(name="Calibri", size=10)

            # Freeze top row
            ws.freeze_panes = "A2"

            # Column dimensions
            col_widths = {
                "A": 26,  # Patient Name
                "B": 12,  # Age/Sex
                "C": 16,  # Hospital ID
                "D": 10,  # Films
                "E": 28,  # Anatomy & Views
                "F": 38,  # Hardware & Implants
                "G": 34,  # Surgeon Remarks
                "H": 44,  # Radiographic Facts
                "I": 35   # Folder Path
            }
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width

            wb.save(file_path)

            # Prompt to open immediately
            reply = QMessageBox.question(
                self,
                "Export Complete",
                f"Successfully exported {len(patients)} patient records to Excel!\n\n"
                f"File: {Path(file_path).name}\n\n"
                "Each patient's name is a clickable hyperlink that opens their folder.\n\n"
                "Would you like to open the Excel spreadsheet now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Could not export to Excel:\n{e}")

    def display_film(self, film_data, title):
        fp = film_data['file_path']
        p = Path(fp)

        # High-performance caching: avoids re-reading and re-decoding from disk on every click
        if fp in self._pixmap_cache:
            pix = self._pixmap_cache[fp]
            self.image_canvas.set_pixmap(pix)
            self.lbl_film_info.setText(f"{p.name}  ·  {title}")
        elif p.exists():
            # Load and downscale to max 1600px once to keep memory lean and scaling instantaneous
            raw_pix = QPixmap(str(p))
            if raw_pix.width() > 1600 or raw_pix.height() > 1600:
                raw_pix = raw_pix.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._pixmap_cache[fp] = raw_pix
            self.image_canvas.set_pixmap(raw_pix)
            self.lbl_film_info.setText(f"{p.name}  ·  {title}")
        else:
            self.image_canvas.setText(f"File not found on disk: {p.name}")
            self.lbl_film_info.setText("")

        part = (film_data.get('body_part') or 'Unknown').title()
        views = format_views(film_data.get('views'))
        dt = film_data.get('study_date') or 'Unknown date'
        self.lbl_active_film_meta.setText(
            f"Anatomy: {part}  ·  Views: {views}\n"
            f"Study Date: {dt}  ·  Path: {p.name}"
        )
        self.current_film_path = p
        self.btn_reveal_film.setEnabled(p.exists())
        self.btn_reveal_film.setToolTip(f"Reveal in Finder: {p}")

    def open_current_patient_folder(self):
        """Opens the active patient's folder directly in Finder / File Explorer."""
        if hasattr(self, "current_patient_folder") and self.current_patient_folder and self.current_patient_folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_patient_folder)))

    def reveal_active_film(self):
        """Reveals the directory containing the currently displayed film."""
        if hasattr(self, "current_film_path") and self.current_film_path and self.current_film_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_film_path.parent)))

    def show_patient_context_menu(self, pos):
        """Context menu on left patient worklist: quick folder access & editing."""
        item = self.patient_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data or not data.get("raw"):
            return
        raw = data["raw"]
        pid = raw["patient_id"]
        name = data.get("name", "Patient")

        menu = QMenu(self)
        act_edit = menu.addAction(f"Edit Findings & Notes for {name}...")
        act_edit.triggered.connect(lambda: self.open_edit_review_dialog(pid))

        menu.addSeparator()

        films = raw.get("films", [])
        if films:
            folder = Path(films[0]["file_path"]).parent
            if folder.exists():
                act_open = menu.addAction(f"Open {name}'s Folder in Finder")
                act_open.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))

        menu.exec(self.patient_list.mapToGlobal(pos))

    def show_table_context_menu(self, pos):
        """Context menu on summary table rows: quick folder access & editing."""
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.visible_patients):
            return
        p = self.visible_patients[row]
        pid = p["patient_id"]
        name = p.get("name", "Patient")

        menu = QMenu(self)
        act_edit = menu.addAction(f"Edit Findings & Notes for {name}...")
        act_edit.triggered.connect(lambda: self.open_edit_review_dialog(pid))

        menu.addSeparator()

        films = p.get("films", [])
        if films:
            folder = Path(films[0]["file_path"]).parent
            if folder.exists():
                act_open = menu.addAction(f"Open {name}'s Folder in Finder")
                act_open.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))

        menu.exec(self.table.mapToGlobal(pos))

    def on_table_double_clicked(self, row, col):
        if row < 0 or row >= len(self.visible_patients):
            return
        self.switch_view(0)
        self.patient_list.setCurrentRow(row)
        self.select_patient_by_index(row)

    # --- DRAG & DROP SUPPORT ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if hasattr(self, 'lbl_drop_banner'):
                self.lbl_drop_banner.setVisible(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            if hasattr(self, 'lbl_drop_banner'):
                self.lbl_drop_banner.setVisible(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        if hasattr(self, 'lbl_drop_banner'):
            self.lbl_drop_banner.setVisible(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if hasattr(self, 'lbl_drop_banner'):
            self.lbl_drop_banner.setVisible(False)
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self.queue_paths(paths)
                event.acceptProposedAction()

    # --- INGESTION QUEUE HANDLERS ---
    def queue_paths(self, paths):
        """Thread-safe enqueueing of folders to background queue with zero interruption."""
        added = self.queue_worker.enqueue_folders(paths)
        if added > 0:
            self.progress_bar.setVisible(True)
            self.btn_pause_queue.setVisible(True)
            self.btn_pause_queue.setText("Pause")
            status = self.queue_worker.get_status()
            self.on_queue_state_changed(status)

    def open_queue_manager(self):
        """Opens the interactive workstation Background Queue Manager modal."""
        dlg = QueueManagerDialog(self.queue_worker, parent=self)
        dlg.exec()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Patient Folder to Enqueue")
        if folder:
            self.queue_paths([folder])

    def choose_batch(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Batch Root Directory (Containing Multiple Patient Folders)")
        if folder:
            self.queue_paths([folder])

    def toggle_queue_pause(self):
        is_paused = self.queue_worker.toggle_pause()
        status = self.queue_worker.get_status()
        self.on_queue_state_changed(status)

    def on_queue_state_changed(self, status):
        """Real-time UI sync for top-bar queue pill and manager button."""
        pending = status.get('pending_count', 0)
        completed = status.get('completed_count', 0)
        total = status.get('total_count', 0)
        is_running = status.get('is_running', False)
        is_paused = status.get('is_paused', False)
        rate = status.get('avg_film_sec', 0.0)
        rate_str = f" · ~{rate}s/film" if rate > 0 else ""

        if is_paused:
            self.btn_manage_queue.setText(f"⏸ Paused ({pending} pending)")
            self.btn_manage_queue.setStyleSheet(
                "background-color: #422006; color: #fde047; border: 1px solid #a16207; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600;"
            )
            self.btn_pause_queue.setText("Resume")
            self.btn_pause_queue.setVisible(True)
        elif is_running:
            cur_f = status.get('current_folder') or 'Analyzing'
            cur_img = status.get('current_film')
            film_hint = f" ({cur_img})" if cur_img else ""
            self.btn_manage_queue.setText(
                f"⚡ Ingesting: {cur_f}{film_hint} · {pending} left{rate_str}"
            )
            self.btn_manage_queue.setStyleSheet(
                "background-color: #172554; color: #93c5fd; border: 1px solid #2563eb; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600;"
            )
            self.btn_pause_queue.setText("Pause")
            self.btn_pause_queue.setVisible(True)
        elif total > 0 and completed >= total:
            total_xrays = status.get('total_xrays', 0)
            self.btn_manage_queue.setText(f"✓ All {completed} studies ready ({total_xrays} films)")
            self.btn_manage_queue.setStyleSheet(
                "background-color: #064e3b; color: #86efac; border: 1px solid #10b981; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600;"
            )
            self.btn_pause_queue.setVisible(False)
        else:
            self.btn_manage_queue.setText("● Queue: Idle")
            self.btn_manage_queue.setStyleSheet(
                "background-color: #12141c; color: #64748b; border: 1px solid #1e2230; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 500;"
            )
            self.btn_pause_queue.setVisible(False)

    def on_queue_updated(self, completed, total, msg):
        status = self.queue_worker.get_status()
        self.on_queue_state_changed(status)

    def on_queue_progress(self, percent, msg):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}% — {msg}")

    def on_patient_ingested(self, patient_id, patient_name, count):
        current_pid = None
        if 0 <= self._current_selected_row < len(self.visible_patients):
            current_pid = self.visible_patients[self._current_selected_row]['patient_id']

        # Zero interruption: reload records silently keeping active patient, active film, and canvas zoom 100% untouched
        self.load_data(preserve_selection_id=current_pid, silent_refresh=True)

        status = self.queue_worker.get_status()
        self.on_queue_state_changed(status)

    def on_queue_all_completed(self, total_folders, total_xrays):
        self.btn_pause_queue.setVisible(False)
        self.progress_bar.setFormat(f"Queue complete: Ingested {total_folders} patient folders ({total_xrays} radiographs).")
        self.load_data(silent_refresh=True)
        status = self.queue_worker.get_status()
        self.on_queue_state_changed(status)

    def on_queue_failed(self, err):
        self.lbl_queue_pill.setText(f"Queue Error: {err}")
        self.lbl_queue_pill.setStyleSheet(
            "background-color: #450a0a; color: #fca5a5; border: 1px solid #dc2626; border-radius: 4px; padding: 4px 10px; font-size: 11px;"
        )
        self.progress_bar.setFormat(f"Error: {err}")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = ImportPage()
    win.setWindowTitle("Orthopedic Study Workstation")
    win.resize(1260, 780)
    win.show()
    sys.exit(app.exec())