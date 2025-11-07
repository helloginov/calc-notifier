import os
from datetime import datetime
from PIL import Image
import io
from matplotlib.figure import Figure

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def save_figure_to_file(fig: Figure, path: str):
    fig.savefig(path, bbox_inches='tight')
    fig.clf()

def assemble_pdf(pdf_path: str, title: str, text: str, image_paths: list) -> bool:
    """
    Собирает PDF: титул (title + text) и затем по одному изображению на странице.
    Возвращает True при успехе.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except Exception:
        return False

    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    # титул
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, height - 30 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, height - 40 * mm, f"Created: {datetime.utcnow().isoformat()} UTC")
    text_y = height - 50 * mm
    c.setFont("Helvetica", 10)
    for line in str(text).splitlines():
        c.drawString(20 * mm, text_y, line[:200])
        text_y -= 6 * mm
        if text_y < 20 * mm:
            c.showPage()
            text_y = height - 30 * mm
    c.showPage()

    for img_path in image_paths:
        try:
            im = Image.open(img_path)
            iw, ih = im.size
            maxw = width - 40 * mm
            maxh = height - 40 * mm
            scale = min(maxw / iw, maxh / ih, 1)
            outw, outh = int(iw * scale), int(ih * scale)
            im = im.resize((outw, outh))
            tmp = img_path + '.tmp.jpg'
            im.convert('RGB').save(tmp, format='JPEG')
            c.drawImage(tmp, 20 * mm, (height - 20 * mm - outh), width=outw, height=outh)
            c.showPage()
            try:
                os.remove(tmp)
            except Exception:
                pass
        except Exception:
            # skip broken image
            continue

    c.save()
    return True

def markdown_v2_escape(text: str) -> str:
    """
    Escape for Telegram MarkdownV2. Minimal but comprehensive.
    """
    if text is None:
        return ""
    # Characters that must be escaped in MarkdownV2
    to_escape = r'_*[]()~`>#+-=|{}.!'
    res = []
    for ch in str(text):
        if ch in to_escape:
            res.append("\\" + ch)
        else:
            res.append(ch)
    return ''.join(res)
