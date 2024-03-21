from zeroconf import ServiceBrowser, ServiceListener, Zeroconf, ZeroconfServiceTypes
from datetime import datetime

class MyListener(ServiceListener):

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        print(f"\n{datetime.now()} Service {name} updated, service info:\n\t{info}")

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        print(f"\n{datetime.now()} Service {name} removed")

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        print(f"\n{datetime.now()} Service {name} added, service info:\n\t{info}")


zeroconf = Zeroconf()
listener = MyListener()
browser = ServiceBrowser(zeroconf, "_raw._tcp.local.", listener)
try:
    input("Press enter to exit...\n\n")
finally:
    zeroconf.close()

print('\n - '.join(ZeroconfServiceTypes.find()))
