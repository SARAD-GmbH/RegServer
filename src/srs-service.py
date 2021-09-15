"""Wrapper to start SARAD Registration Server as Windows service"""
import socket
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

import registrationserver.main


class SaradRegistrationServer(win32serviceutil.ServiceFramework):
    _svc_name_ = "SaradRegistrationServer"
    _svc_display_name_ = "SARAD Registration Server"
    _svc_description_ = (
        "Provides connection to local and remote "
        + "measuring instruments from SARAD GmbH"
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        registrationserver.main.set_file_flag(False)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        registrationserver.main.main()


if __name__ == "__main__":
    # Pyinstaller fix
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SaradRegistrationServer)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SaradRegistrationServer)
