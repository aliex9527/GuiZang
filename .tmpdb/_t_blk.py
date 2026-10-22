import os, sys
sys.path.insert(0, r"D:/WorkBuddy/2026-10-21-12-38-50")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from core.database import Database
from ui.main_window import MainWindow
from ui.database_view import DatabaseView

app = QApplication(sys.argv)
db = Database(r"D:/WorkBuddy/2026-10-21-12-38-50/.tmpdb/t.db")
w = MainWindow(db); w.resize(1000, 680); w.show()
for _ in range(4): app.processEvents()
view = w.findChildren(DatabaseView)[0]
ed = view.editor
nid = db.create_node("t"); view._reload_tree(select_id=nid); view._select_node(nid)
for _ in range(3): app.processEvents()

def case(label, key, mods):
    ed.set_node(nid, "", "md")
    for _ in range(3): app.processEvents()
    view.tree.setFocus(); app.processEvents()   # 故意把焦点放树里
    QTest.keyClick(view.tree, key, mods)
    app.processEvents()
    ed.edit.insertPlainText("x")
    app.processEvents()
    print(f"{label:<12} 焦点={type(app.focusWidget()).__name__:<13} md={ed.payload()[1]!r}")

C, S = Qt.ControlModifier, Qt.ShiftModifier
case("Ctrl+1", Qt.Key_1, C)
case("Ctrl+Shift+Q", Qt.Key_Q, C | S)
case("Ctrl+Shift+[", Qt.Key_BracketLeft, C | S)
case("Ctrl+Shift+X", Qt.Key_X, C | S)
case("Ctrl+Shift+K", Qt.Key_K, C | S)
case("Ctrl+Shift+`", Qt.Key_QuoteLeft, C | S)
case("Alt+Shift+5", Qt.Key_5, Qt.AltModifier | S)
