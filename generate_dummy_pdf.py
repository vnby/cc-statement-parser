from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

def create_dummy_pdf(filename):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    
    # Header
    elements.append(Paragraph("CREDIT CARD STATEMENT", styles['Title']))
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph("John Doe", styles['Normal']))
    elements.append(Paragraph("1234 Main St", styles['Normal']))
    elements.append(Paragraph("Anytown, USA 12345", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    elements.append(Paragraph("Statement Period: Jan 01, 2025 - Jan 31, 2025", styles['Heading2']))
    elements.append(Spacer(1, 10))
    
    # Data
    data = [
        ['Date', 'Description', 'Amount'],
        ['01/02/2025', 'GROCERY STORE INC', '54.23'],
        ['01/05/2025', 'GAS STATION 101', '45.00'],
        ['01/10/2025', 'ONLINE BOOKSTORE', '12.99'],
        ['01/15/2025', 'RESTAURANT CHEZ PIERRE', '89.50'],
        ['01/20/2025', 'SUBSCRIPTION SERVICE', '14.99'],
        ['01/25/2025', 'REFUND - ONLINE STORE', '-10.00'],
        ['01/28/2025', 'COFFEE SHOP', '4.50'],
    ]
    
    # Table Style
    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    elements.append(t)
    
    # Footer
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("Total Balance Due: $211.21", styles['Heading3']))
    
    doc.build(elements)
    print(f"Generated {filename}")

if __name__ == "__main__":
    create_dummy_pdf("dummy_statement.pdf")
