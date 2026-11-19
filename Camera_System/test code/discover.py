from onvif import ONVIFCamera
from getpass import getpass
 
IP = "192.168.1.10"
PORT = 80
 
USERNAME = input("DVR username [admin]: ") or "admin"
PASSWORD = getpass("DVR password: ")

try:
    camera = ONVIFCamera(IP, PORT, USERNAME, PASSWORD)
    media = camera.create_media_service()
 
    profiles = media.GetProfiles()
 
    for profile in profiles:
        request = media.create_type("GetStreamUri")
        request.StreamSetup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"}
        }
        request.ProfileToken = profile.token
 
        uri = media.GetStreamUri(request)
 
        print(f"\nProfile: {profile.Name}")
        print(f"RTSP URL: {uri.Uri}")
 
except Exception as e:
    print(f"Error: {e}")