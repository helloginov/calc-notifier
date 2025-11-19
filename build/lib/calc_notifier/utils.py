import os
from datetime import datetime, timezone
from io import BytesIO
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, KeepInFrame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Frame, PageTemplate, BaseDocTemplate
from reportlab.lib import colors


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_figure_to_file(fig, path: str):
    fig.savefig(path, bbox_inches='tight', dpi=200, facecolor='white', edgecolor='none')
    fig.clf()


def html_escape(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def assemble_pdf(pdf_path: str, title: str, text: str, image_paths: list) -> bool:
    try:
        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            leftMargin=20*mm,
            rightMargin=20*mm,
            topMargin=20*mm,
            bottomMargin=20*mm
        )

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='TitleCenter', fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=20))
        styles.add(ParagraphStyle(name='NormalSmall', parent=styles['Normal'], fontSize=9))
        styles.add(ParagraphStyle(name='Code', parent=styles['Code'], fontSize=8, leading=10))

        story = []

        # Заголовок
        story.append(Paragraph(title or "Report", styles['TitleCenter']))
        story.append(Paragraph(f"Created: {datetime.now(timezone.utc).isoformat()} UTC", styles['NormalSmall']))
        story.append(Spacer(1, 12))

        # Текст
        if text:
            text_html = html_escape(text).replace("\n", "<br/>")
            story.append(Paragraph(text_html, styles['Normal']))
            story.append(Spacer(1, 20))

        story.append(PageBreak())

        # Изображения
        for img_path in image_paths:
            try:
                img = Image.open(img_path)
                img_width, img_height = img.size
                max_width = 160*mm
                max_height = 220*mm

                ratio = min(max_width / img_width, max_height / img_height)
                new_width = img_width * ratio
                new_height = img_height * ratio

                rl_img = RLImage(img_path, width=new_width, height=new_height)
                rl_img.hAlign = 'CENTER'

                frame = Frame(20*mm, 20*mm, 160*mm, 220*mm, showBoundary=0)
                story.append(KeepInFrame(160*mm, 220*mm, [rl_img], hAlign='CENTER', vAlign='MIDDLE'))
                story.append(PageBreak())
            except Exception as e:
                story.append(Paragraph(f"<i>Failed to add image: {img_path}</i>", styles['Normal']))

        # Добавляем нумерацию страниц
        def add_page_number(canvas, doc):
            page_num = canvas.getPageNumber()
            canvas.setFont("Helvetica", 9)
            canvas.drawRightString(doc.rightMargin + doc.width, doc.bottomMargin - 10,
                                   f"Page {page_num}")

        doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
        return True
    except Exception as e:
        print(f"Failed to generate PDF: {e}")
        return False