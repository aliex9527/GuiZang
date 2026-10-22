import os, sys
sys.path.insert(0, r"D:/WorkBuddy/2026-10-21-12-38-50")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextDocument
from ui.md_source import markdown_to_html, document_to_markdown

app = QApplication(sys.argv)
CASES = [
 ("h1", "# 标题一\n"), ("h3", "### 三级标题\n"),
 ("bold", "这是 **粗体** 和 *斜体* 和 ~~删除~~\n"),
 ("inline_code", "跑 `pip install x` 看看\n"),
 ("ul", "- 甲\n- 乙\n- 丙\n"), ("ol", "1. 一\n2. 二\n3. 三\n"),
 ("nested", "- 甲\n    - 甲一\n    - 甲二\n- 乙\n"),
 ("quote", "> 引用一行\n> 引用二行\n"),
 ("code", "```\nprint(1)\nprint(2)\n```\n"),
 ("table", "| a | b |\n| --- | --- |\n| 1 | 2 |\n"),
 ("task", "- [ ] 待做\n- [x] 已做\n"),
 ("hr", "上线前\n\n---\n\n上线后\n"),
 ("link", "看 [官网](https://example.com) 吧\n"),
 ("highlight", "这里 ==很重要== 的\n"),
 ("img", "![图](gzs:///7)\n"),
]
ok = bad = 0
for name, src in CASES:
    d = QTextDocument(); d.setHtml(markdown_to_html(src))
    out = document_to_markdown(d)
    if out.strip() == src.strip(): ok += 1
    else:
        bad += 1
        print(f"[FAIL] {name}\n  in : {src!r}\n  out: {out!r}")
print(f"--- {ok} passed, {bad} failed ---")
