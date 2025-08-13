from node import Node
import csv

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
            messages.append(("warning", f"{node.id}: Input voltage {node.nom_in_voltage}V is below nominal output voltage {node.nom_out_voltage}V"))
        if node.nom_in_current < node.nom_out_current:
            messages.append(("warning", f"{node.id}: Input current {node.nom_in_current}A is below nominal output current {node.nom_out_current}A"))

        if node.nom_in_voltage > node.max_in_voltage:
            messages.append(("error", f"{node.id}: Input voltage {node.nom_in_voltage}V exceeds max {node.max_in_voltage}V"))
        if node.nom_in_current > node.max_in_current:
            messages.append(("error", f"{node.id}: Input current {node.nom_in_current}A exceeds max {node.max_in_current}A"))

        total_child_voltage = 0
        total_child_current = 0
        for child in node.children:
            total_child_voltage = max(total_child_voltage, child.nom_in_voltage)
            total_child_current += child.nom_in_current

        if total_child_voltage > node.max_out_voltage:
            messages.append(("error", f"{node.id}: Required output voltage {total_child_voltage}V exceeds max {node.max_out_voltage}V"))
        if total_child_current > node.max_out_current:
            messages.append(("error", f"{node.id}: Total output current {total_child_current}A exceeds max {node.max_out_current}A"))

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