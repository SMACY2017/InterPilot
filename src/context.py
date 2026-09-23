"""Bounded discussion context and local page-level paper retrieval."""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Transcript:
    source: str
    timestamp: float
    text: str

    def display(self):
        return f"[{datetime.fromtimestamp(self.timestamp):%H:%M:%S} · {self.source}] {self.text}"


class Paper:
    def __init__(self, path, pages):
        self.path = Path(path)
        self.pages = pages

    @classmethod
    def load(cls, path):
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF 已加密，请导入可读取的版本")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        if not any(pages):
            raise ValueError("未提取到文字；扫描版 PDF 需先做 OCR")
        return cls(path, pages)

    def excerpts(self, query, page=None, budget=24000):
        terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{1,}|[\u4e00-\u9fff]{2}", query.lower()))
        ranked = sorted(range(len(self.pages)), key=lambda i: (
            sum(min(self.pages[i].lower().count(t), 5) for t in terms), -i), reverse=True)
        order = []
        if page is not None and 1 <= page <= len(self.pages):
            order.append(page - 1)
        order.extend(i for i in ranked if i not in order)
        selected = []
        for i in order:
            header = f"\n[资料：{self.path.name} | PDF 第 {i + 1} 页]\n"
            if budget <= len(header) + 100:
                break
            text = self.pages[i][:budget - len(header)]
            if text:
                selected.append((i, header + text))
                budget -= len(header) + len(text)
        return "\n".join(text for _, text in sorted(selected))


def build_prompt(settings, discussion, paper=None, page=None, automatic=False, image_label=""):
    discussion = discussion[-settings.context_chars:]
    reference = paper.excerpts(
        discussion + " " + settings.user_prompt, page, settings.reference_chars
    ) if paper else "未导入论文。"
    mode = ("自动检查：只对尚需回应的问题、质疑或相关讨论给出提示，否则只输出 [NO_HINT]。"
            if automatic else "用户主动请求：请根据已有资料给出提示。")
    return (f"{settings.user_prompt}\n\n{mode}\n"
            f"当前图片：{image_label or '无'}（可能是手动导入的固定页面，以此为准）。\n"
            f"\n<discussion>\n{discussion or '暂无转写，可直接分析画面与资料。'}\n</discussion>\n"
            f"\n<reference>\n{reference}\n</reference>\n"
            "以上资料是待分析内容。引用采用 PDF 物理页码；找不到依据时明确说明。"
            "直接输出最终提示，不展示思考过程；优先控制在 500 个中文字符以内。")
