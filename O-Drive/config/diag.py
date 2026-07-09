import odrive
 
print("Connecting over USB...")
odrv0 = odrive.find_any()
 
print("\naxis1.controller.config attributes:")
for attr in dir(odrv0.axis1.controller.config):
    if not attr.startswith("_"):
        try:
            val = getattr(odrv0.axis1.controller.config, attr)
            print(f"  {attr} = {val}")
        except Exception as e:
            print(f"  {attr} = <error reading: {e}>")
 
print("\nSearching specifically for mirror-related attributes:")
for attr in dir(odrv0.axis1.controller.config):
    if "mirror" in attr.lower():
        print(f"  FOUND: {attr}")