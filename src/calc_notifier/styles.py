from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

def get_styles():
    styles = getSampleStyleSheet()
    
    # Не переопределяем уже существующий стиль Code
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
    if 'Mono' not in styles:  # вместо Code
        styles.add(ParagraphStyle(
            name='Mono',
            fontName='Courier',
            fontSize=8,
            leading=10
        ))
    return styles