import subprocess
import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
 
# Change this to match your Ethernet subnet
NETWORK = ipaddress.ip_network("192.168.1.0/24")
 
def scan(ip):
    ip = str(ip)
    result = subprocess.run(
        ["ping", "-n", "1", "-w", "300", ip],
        capture_output=True,
        text=True
    )
 
    if result.returncode == 0:
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except OSError:
            hostname = "Unknown"
 
        return ip, hostname
 
with ThreadPoolExecutor(max_workers=40) as executor:
    results = executor.map(scan, NETWORK.hosts())
 
    for result in results:
        if result:
            print(f"Device found: {result[0]} | {result[1]}")