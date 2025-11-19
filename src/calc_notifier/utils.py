import os
import threading
from datetime import datetime, timezone
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, KeepInFrame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from matplotlib.figure import Figure
import matplotlib.pyplot as plt


def ensure_dir(path: str):
    """Create directory if it does not exist."""
    os.makedirs(path, exist_ok=True)


class MatplotlibThreadSafetyError(RuntimeError):
    """Raised when user tries to save a matplotlib figure from a background thread with a GUI backend."""
    pass


def save_figure_to_file(fig: Figure, path: str):
    """Save matplotlib figure safely. Raises clear error if called from non-main thread with GUI backend."""
    if threading.current_thread() is not threading.main_thread():
        backend = plt.get_backend().lower()
        if 'agg' not in backend and backend != 'inline':
            raise MatplotlibThreadSafetyError(
                "Attempt to save matplotlib figure from a background thread!\n\n"
                f"Current backend: {backend.upper()}\n"
                "GUI backends (TkAgg, Qt5Agg, etc.) are not thread-safe on Windows.\n\n"
                "Solution:\n"
                "Add the following lines at the very beginning of your script:\n"
                "    import matplotlib; matplotlib.use('Agg')\n\n"
                "Or create and save figures only in the main thread."
            )

    fig.savefig(path, bbox_inches='tight', dpi=200, facecolor='white', edgecolor='none')
    fig.clf()
    plt.close(fig)


def html_escape(text: str) -> str:
    """Simple HTML escaping for Telegram."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_styles():
    styles = getSampleStyleSheet()
    if 'TitleCenter' not in styles:
        styles.add(ParagraphStyle(
            name='TitleCenter',
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=20
        ))
    if 'NormalSmall' not in styles:
        styles.add(ParagraphStyle(
            name='NormalSmall',
            parent=styles['Normal'],
            fontSize=9
        ))
    return styles


def assemble_pdf(pdf_path: str, title: str, text: str, image_paths: list) -> bool:
    """Generate PDF report with title, text and images (one per page)."""
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm
    )

    styles = get_styles()
    story = []

    # Header
    story.append(Paragraph(title or "Report", styles['TitleCenter']))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()} UTC", styles['NormalSmall']))
    story.append(Spacer(1, 12))

    # Main text
    if text and text.strip():
        escaped = html_escape(text).replace("\n", "<br/>")
        story.append(Paragraph(escaped, styles['Normal']))
        story.append(Spacer(1, 20))

    story.append(PageBreak())

    # Images – one per page
    for img_path in image_paths:
        if not os.path.exists(img_path):
            story.append(Paragraph(f"<i>Missing image: {os.path.basename(img_path)}</i>", styles['Normal']))
            continue
        try:
            img = Image.open(img_path)
            img_width, img_height = img.size

            max_width = 160 * mm
            max_height = 220 * mm
            ratio = min(max_width / img_width, max_height / img_height)
            new_width = img_width * ratio
            new_height = img_height * ratio

            rl_img = RLImage(img_path, width=new_width, height=new_height)
            rl_img.hAlign = 'CENTER'

            story.append(KeepInFrame(max_width, max_height, [rl_img], hAlign='CENTER', vAlign='MIDDLE'))
            story.append(PageBreak())
        except Exception as e:
            story.append(Paragraph(f"<i>Failed to add image {os.path.basename(img_path)}: {e}</i>", styles['Normal']))
            story.append(PageBreak())

    # Page numbers
    def add_page_number(canvas, doc):
        page_num = canvas.getPageNumber()
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(doc.rightMargin + doc.width, doc.bottomMargin - 10, f"Page {page_num}")

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return True