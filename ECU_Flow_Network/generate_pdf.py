import csv
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

def generate_pdf_report(errors, warnings, supply_data, output_file="ecu_report.pdf"):
    doc = SimpleDocTemplate(output_file, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph("ECU Network Diagnostic Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Errors
    if errors:
        elements.append(Paragraph("Errors", styles['Heading2']))
        for err in errors:
            elements.append(Paragraph(f"- {err}", styles['Normal']))
        elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph("No errors detected.", styles['Normal']))
        elements.append(Spacer(1, 12))

    # Warnings
    if warnings:
        elements.append(Paragraph("Warnings", styles['Heading2']))
        for warn in warnings:
            elements.append(Paragraph(f"- {warn}", styles['Normal']))
        elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph("No warnings detected.", styles['Normal']))
        elements.append(Spacer(1, 12))

   # Supply Requirements Table
    elements.append(Paragraph("Supply Requirements", styles['Heading2']))
    table_data = [["Metric", "Value", "Unit"],
                ["Voltage Needed", f"{supply_data[0]:.2f}", "V"],
                ["Current Needed", f"{supply_data[1]:.2f}", "A"],
                ["Total Power Draw", f"{supply_data[2]:.2f}", "W"]]

    table = Table(table_data, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.black),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)

    # Save PDF
    doc.build(elements)