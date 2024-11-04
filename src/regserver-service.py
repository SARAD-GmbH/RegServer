#!/usr/bin/env python3
"""Wrapper to start SARAD Registration Server as Windows service

:Created:
    2021-10-21

:Author:
    | Michael Strey <strey@sarad.de>
"""
import multiprocessing
import socket
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

import regserver.main
from regserver.shutdown import system_shutdown
from regserver.version import VERSION


class SaradRegistrationServer(win32serviceutil.ServiceFramework):
    """SaradRegistrationServer service"""

    _svc_name_ = "SaradRegistrationServer"
    _svc_display_name_ = "SARAD Registration Server"
    _svc_description_ = (
        "Provides connection to local and remote "
        + "measuring instruments from SARAD GmbH. "
        + VERSION
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    def GetAcceptedControls(self):
        """Override the base class so we can accept additional events.

        say we accept them all.

        """
        rc = win32serviceutil.ServiceFramework.GetAcceptedControls(self)
        rc = (
            rc
            | win32service.SERVICE_ACCEPT_PRESHUTDOWN
            | win32service.SERVICE_ACCEPT_SHUTDOWN
            | win32service.SERVICE_ACCEPT_POWEREVENT
        )
        return rc

    def service_shutdown(self, with_error):
        """Shutdown of the Windows service"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        system_shutdown(with_error=with_error)

    def SvcOtherEx(self, control, event_type, data):
        """All extra events are sent via SvcOtherEx (SvcOther remains as a
        function taking only the first args for backwards compat) This is only
        showing a few of the extra events - see the MSDN docs for "HandlerEx
        callback" for more info.

        """
        if control == win32service.SERVICE_CONTROL_PRESHUTDOWN:
            servicemanager.LogInfoMsg("Preshutdown event: Trying to shutdown service")
            self.service_shutdown(False)
        elif control == win32service.SERVICE_CONTROL_POWEREVENT:
            servicemanager.LogInfoMsg(
                f"Power event: code={control}, type={event_type}, data={data}"
            )
            if event_type in (6, 7):
                servicemanager.LogInfoMsg("Resumed: Shutting down service for restart")
                self.service_shutdown(True)
        else:
            servicemanager.LogInfoMsg(
                f"Other event: code={control}, type={event_type}, data={data}"
            )

    def SvcStop(self):
        """Function that will be performed on 'service stop'.

        Removes the flag file to cause the main loop to stop."""
        self.service_shutdown(False)

    def SvcDoRun(self):
        """Function that will be performed on 'service start'.

        Starts the main function of the Registration Server"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        regserver.main.Main().main()


def main():
    """Main function of the SARAD Registration Server Service for Windows"""
    # Pyinstaller fix
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SaradRegistrationServer)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SaradRegistrationServer)


if __name__ == "__main__":
    main()
