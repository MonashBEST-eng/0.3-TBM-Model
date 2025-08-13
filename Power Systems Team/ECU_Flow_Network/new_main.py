import csv
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

import dash
from dash import html, Output, Input
import dash_cytoscape as cyto

# === ECU NETWORK LOGIC ===
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
            messages.append(("warning", f"Input voltage {node.nom_in_voltage}V < nominal output {node.nom_out_voltage}V"))
        if node.nom_in_current < node.nom_out_current:
            messages.append(("warning", f"Input current {node.nom_in_current}A < nominal output {node.nom_out_current}A"))

        if node.nom_in_voltage > node.max_in_voltage:
            messages.append(("error", f"Input voltage {node.nom_in_voltage}V > max {node.max_in_voltage}V"))
        if node.nom_in_current > node.max_in_current:
            messages.append(("error", f"Input current {node.nom_in_current}A > max {node.max_in_current}A"))

        total_child_voltage = 0
        total_child_current = 0
        for child in node.children:
            total_child_voltage = max(total_child_voltage, child.nom_in_voltage)
            total_child_current += child.nom_in_current

        if total_child_voltage > node.max_out_voltage:
            messages.append(("error", f"Required output voltage {total_child_voltage}V > max {node.max_out_voltage}V"))
        if total_child_current > node.max_out_current:
            messages.append(("error", f"Total output current {total_child_current}A > max {node.max_out_current}A"))

        return messages

    def analyze(self):
        errors = []
        warnings = []
        for node in self.nodes.values():
            msgs = self.validate_node(node)
            for level, msg in msgs:
                if level == "error":
                    errors.append((node.id, msg))
                else:
                    warnings.append((node.id, msg))
        return errors, warnings

    def calculate_supply_requirements(self):
        supply_voltage = max(node.nom_in_voltage for node in self.nodes.values())
        supply_current = sum(node.nom_in_current for node in self.nodes.values())
        total_power = sum(node.nom_in_voltage * node.nom_in_current for node in self.nodes.values())
        return supply_voltage, supply_current, total_power

# === PDF REPORT FUNCTION ===
def generate_pdf_report(errors, warnings, supply_data, output_file="ecu_report.pdf"):
    doc = SimpleDocTemplate(output_file, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph("ECU Network Diagnostic Report", styles['Title']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Errors
    elements.append(Paragraph("Errors", styles['Heading2']))
    if errors:
        for node_id, err in errors:
            elements.append(Paragraph(f"- Node {node_id}: {err}", styles['Normal']))
    else:
        elements.append(Paragraph("No errors detected.", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Warnings
    elements.append(Paragraph("Warnings", styles['Heading2']))
    if warnings:
        for node_id, warn in warnings:
            elements.append(Paragraph(f"- Node {node_id}: {warn}", styles['Normal']))
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
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)
    doc.build(elements)
    print(f"📄 PDF report generated: {output_file}")

# === DASH CYTOSCAPE UI ===
app = dash.Dash(__name__)

def create_elements(nodes, errors, warnings):
    elements = []
    for node_id, node in nodes.items():
        # Calculate node power = nominal voltage * nominal current
        node_power = node.nom_in_voltage * node.nom_in_current
        elements.append({
            'data': {
                'id': node_id,
                'label': node_id,  # Node name
                'voltage': node.nom_in_voltage,
                'current': node.nom_in_current,
                'power': node_power
            }
        })

    # Add edges: parent -> child
    for node_id, node in nodes.items():
        for child in node.children:
            # Check if there is an error/warning on child node
            desc = ""
            edge_class = ""
            for e_node, msg in errors + warnings:
                if e_node == child.id:
                    desc += msg + " "
                    edge_class = "error-edge" if (e_node, msg) in errors else "warning-edge"
            elements.append({
                'data': {
                    'source': node_id,
                    'target': child.id,
                    'label': f"{node_id}-{child.id}",
                    'description': desc.strip()
                },
                'classes': edge_class
            })
    return elements

# === MAIN ===
csv_path = "error.csv"  # CSV path
network = ECUNetwork(csv_path)
errors, warnings = network.analyze()
supply_data = network.calculate_supply_requirements()

# Generate PDF
generate_pdf_report(errors, warnings, supply_data, output_file="ecu_diagnostic_report.pdf")

# Create Cytoscape elements
elements = create_elements(network.nodes, errors, warnings)

app.layout = html.Div([
    cyto.Cytoscape(
        id='cytoscape-network',
        elements=elements,
        style={'width': '100%', 'height': '600px'},
        stylesheet=[
            {'selector': 'node',
             'style': {
                 'content': 'data(label)',
                 'background-color': '#0074D9',
                 'color': 'black',
                 'text-valign': 'center',
                 'text-halign': 'center',
                 'font-size': 14,
                 'width': 60,
                 'height': 60
             }},
            {'selector': 'edge', 'style': {'line-color': '#ccc', 'width': 2}},
            {'selector': '.warning-edge', 'style': {'line-color': 'yellow', 'width': 4}},
            {'selector': '.error-edge', 'style': {'line-color': 'red', 'width': 4}}
        ]
    ),
    html.Div(id='tooltip-div', style={'marginTop': '20px', 'fontWeight': 'bold'})
])

@app.callback(
    Output('tooltip-div', 'children'),
    Input('cytoscape-network', 'mouseoverNodeData'),
    Input('cytoscape-network', 'mouseoverEdgeData')
)
def display_tooltip(node_data, edge_data):
    if node_data:
        voltage = node_data.get('voltage', 0)
        current = node_data.get('current', 0)
        power = node_data.get('power', 0)
        return f"Node {node_data['label']} — Voltage: {voltage} V, Current: {current} A, Power: {power} W"
    elif edge_data:
        return f"Edge {edge_data['label']} — {edge_data.get('description','')}"
    return "Hover over a node or edge"

if __name__ == '__main__':
    app.run(debug=True)