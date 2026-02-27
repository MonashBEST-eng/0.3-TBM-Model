from ecu_network import ECUNetwork
from generate_pdf import generate_pdf_report

csv_path = "error.csv"  # CSV file path
network = ECUNetwork(csv_path)

# Run analysis
errors, warnings = network.analyze()
supply_data = network.calculate_supply_requirements()

# Generate PDF
generate_pdf_report(errors, warnings, supply_data, output_file="ecu_diagnostic_report.pdf")