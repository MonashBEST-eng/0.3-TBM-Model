import csv

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

        # Warning if nominal input less than nominal output
        if node.nom_in_voltage < node.nom_out_voltage:
            messages.append(("warning", f"Node {node.id}: Input voltage {node.nom_in_voltage}V is below nominal output voltage {node.nom_out_voltage}V"))
        if node.nom_in_current < node.nom_out_current:
            messages.append(("warning", f"Node {node.id}: Input current {node.nom_in_current}A is below nominal output current {node.nom_out_current}A"))

        # Error if nominal input exceeds max input
        if node.nom_in_voltage > node.max_in_voltage:
            messages.append(("error", f"Node {node.id}: Input voltage {node.nom_in_voltage}V exceeds max {node.max_in_voltage}V"))
        if node.nom_in_current > node.max_in_current:
            messages.append(("error", f"Node {node.id}: Input current {node.nom_in_current}A exceeds max {node.max_in_current}A"))

        # Check output constraints vs children
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
        print("🔍 Analyzing ECU network...\n")
        errors = 0
        warnings = 0

        for node in self.nodes.values():
            messages = self.validate_node(node)
            for level, msg in messages:
                if level == "error":
                    print(f"❌ ERROR: {msg}")
                    errors += 1
                else:
                    print(f"⚠️ WARNING: {msg}")
                    warnings += 1

        if errors == 0:
            print("\n✅ No errors detected. Network is valid.")
        else:
            print(f"\n❌ Found {errors} error(s) in the network.")

        if warnings > 0:
            print(f"⚠️ Found {warnings} warning(s) — review recommended.")

    def calculate_supply_requirements(self):
        # Find max voltage required across all nodes (supply voltage must be at least this)
        supply_voltage = max(node.nom_in_voltage for node in self.nodes.values())
        # Sum all nominal input currents (supply current must cover total current demand)
        supply_current = sum(node.nom_in_current for node in self.nodes.values())
        # Total power = sum of voltage * current per node (could also be supply_voltage * supply_current as approx)
        total_power = sum(node.nom_in_voltage * node.nom_in_current for node in self.nodes.values())

        print("\n⚡ Supply requirements to run the network:")
        print(f"   Voltage needed: {supply_voltage:.2f} V")
        print(f"   Current needed: {supply_current:.2f} A")
        print(f"   Total power draw: {total_power:.2f} W")


# === USAGE ===
if __name__ == "__main__":
    csv_path = "error.csv"  # Adjust filename/path as needed
    network = ECUNetwork(csv_path)
    network.analyze()
    network.calculate_supply_requirements()
