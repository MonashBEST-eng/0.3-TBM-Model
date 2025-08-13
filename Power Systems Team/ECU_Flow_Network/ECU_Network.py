import csv
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors


class Node:
    def __init__(self, row):
        self.id = row["id"]
        self.parent_id = row["parent_id"] if row["parent_id"] != '' else None
        self.nom_in_voltage = float(row["Nominal Input Voltage (V)"])
        self.nom_in_current = float(row["Nominal Input Current (A)"])
        self.max_in_voltage = float(row["Max Input Voltage (V)"])
        self.max_in_current = float(row["Max Input Current (A)"])
        self.nom_out_voltage = float(row["Nominal Output Voltage (V)"])
        self.nom_out_current = float(row["Nominal Output Current (A)"])
        self.max_out_voltage = float(row["Max Output Voltage (V)"])
        self.max_out_current = float(row["Max Output Current (A)"])
        self.children = []

    def add_child(self, child):
        self.children.append(child)


class ECUNetwork:
    def __init__(self, csv_file_path):
        self.nodes = {}
        self.root = None
        self.load_nodes(csv_file_path)

    def load_nodes(self, csv_file_path):
        with open(csv_file_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                node = Node(row)
                self.nodes[node.id] = node

        # Build tree relationships
        for node in self.nodes.values():
            if node.parent_id:
                parent = self.nodes.get(node.parent_id)
                if parent:
                    parent.add_child(node)
            else:
                self.root = node

    def validate_node(self, node):
        messages = []
        if node.nom_in_voltage < node.nom_out_voltage:
            messages.append(("warning", f"Node {node.id}: Input voltage {node.nom_in_voltage}V is below nominal output voltage {node.nom_out_voltage}V"))
        if node.nom_in_current < node.nom_out_current:
            messages.append(("warning", f"Node {node.id}: Input current {node.nom_in_current}A is below nominal output current {node.nom_out_current}A"))

        if node.nom_in_voltage > node.max_in_voltage:
            messages.append(("error", f"Node {node.id}: Input voltage {node.nom_in_voltage}V exceeds max {node.max_in_voltage}V"))
        if node.nom_in_current > node.max_in_current:
            messages.append(("error", f"Node {node.id}: Input current {node.nom_in_current}A exceeds max {node.max_in_current}A"))

        total_child_voltage = 0
        total_child_current = 0
        for child in node.children:
            total_child_voltage = max(total_child_voltage, child.nom_in_voltage)
            total_child_current += child.nom_in_current

        if total_child_voltage > node.max_out_voltage:
            messages.append(("error", f"Node {node.id}: Required output voltage {total_child_voltage}V exceeds max {node.max_out_voltage}V"))
        if total_child_current > node.max_out_current:
            messages.append(("error", f"Node {node.id}: Total output current {total_child_current}A exceeds max {node.max_out_current}A"))

        return messages

    def analyze(self):
        errors = []
        warnings = []
        for node in self.nodes.values():
            messages = self.validate_node(node)
            for level, msg in messages:
                if level == "error":
                    errors.append(msg)
                else:
                    warnings.append(msg)
        return errors, warnings

    def calculate_supply_requirements(self):
        supply_voltage = max(node.nom_in_voltage for node in self.nodes.values())
        supply_current = sum(node.nom_in_current for node in self.nodes.values())
        total_power = sum(node.nom_in_voltage * node.nom_in_current for node in self.nodes.values())
        return supply_voltage, supply_current, total_power


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
    print(f"\n📄 PDF report generated: {output_file}")


# === MAIN ===
if __name__ == "__main__":
    csv_path = "error.csv"  # CSV file path
    network = ECUNetwork(csv_path)

    # Run analysis
    errors, warnings = network.analyze()
    supply_data = network.calculate_supply_requirements()

    # Generate PDF
    generate_pdf_report(errors, warnings, supply_data, output_file="ecu_diagnostic_report.pdf")
