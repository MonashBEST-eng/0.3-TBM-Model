from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery

wsd = WSDiscovery()
wsd.start()

try:
    services = wsd.searchServices()

    if not services:
        print("No ONVIF devices discovered.")
    else:
        for service in services:
            print("Device found!")
            print("Addresses:", service.getXAddrs())
finally:
    wsd.stop()
