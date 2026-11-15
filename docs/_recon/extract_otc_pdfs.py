import sys, os
sys.stdout.reconfigure(encoding="utf-8")
from pypdf import PdfReader

base = r"C:\Users\Xingyu Liu\Desktop\autocallables-pricing\docs"
out_dir = r"C:\Users\Xingyu Liu\Desktop\Balanced Portfolio\docs\otc"
os.makedirs(out_dir, exist_ok=True)

mapping = {
    "雪球期权定价测试.pdf": "snowball-test.md",
    "凤凰期权定价测试.pdf": "phoenix-test.md",
    "障碍期权定价测试.pdf": "barrier-test.md",
    "气囊结构定价测试.pdf": "airbag-test.md",
}

for pdf, md in mapping.items():
    path = os.path.join(base, pdf)
    reader = PdfReader(path)
    parts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        parts.append(f"\n## [Page {i+1}]\n\n" + text.strip())
    content = "\n".join(parts)
    target = os.path.join(out_dir, md)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(md, "pages:", len(reader.pages), "chars:", len(content))
