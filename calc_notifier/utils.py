import os
from datetime import datetime
from PIL import Image


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_figure_to_file(fig, path: str):
    # fig: matplotlib.figure.Figure
    # сохраняем в PNG
    fig.savefig(path, bbox_inches='tight')


def assemble_pdf_if_possible(pdf_path: str, title: str, extra_info: dict, image_paths: list) -> bool:
    """Пробуем собрать простой pdf из изображений и текста. Если reportlab не установлен — возвращаем False."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except Exception:
        return False

    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    # титульная страница
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, height - 30 * mm, title)
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, height - 40 * mm, f"Created: {datetime.now(datetime.timezone.utc).isoformat()} UTC")
    y = height - 50 * mm
    for k, v in (extra_info or {}).items():
        c.drawString(20 * mm, y, f"{k}: {v}")
        y -= 6 * mm
    c.showPage()

    for img in image_paths:
        try:
            im = Image.open(img)
            iw, ih = im.size
            # fit to page with margins
            maxw = width - 40 * mm
            maxh = height - 40 * mm
            scale = min(maxw / iw, maxh / ih, 1)
            outw, outh = int(iw * scale), int(ih * scale)
            im = im.resize((outw, outh))
            tmp = img + '.tmp.jpg'
            im.save(tmp, format='JPEG')
            c.drawImage(tmp, 20 * mm, (height - 20 * mm - outh), width=outw, height=outh)
            c.showPage()
            try:
                os.remove(tmp)
            except Exception:
                pass
        except Exception:
            continue
    c.save()
    return True