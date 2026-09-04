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