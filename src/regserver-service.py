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
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    # Override the base class so we can accept additional events.
    def GetAcceptedControls(self):
        # say we accept them all.
        rc = win32serviceutil.ServiceFramework.GetAcceptedControls(self)
        rc |= (
            win32service.SERVICE_ACCEPT_PRESHUTDOWN
            | win32service.SERVICE_ACCEPT_POWEREVENT
        )
        return rc

    # All extra events are sent via SvcOtherEx (SvcOther remains as a
    # function taking only the first args for backwards compat)
    def SvcOtherEx(self, control, event_type, data):
        # This is only showing a few of the extra events - see the MSDN
        # docs for "HandlerEx callback" for more info.
        if control == win32service.SERVICE_ACCEPT_PRESHUTDOWN:
            msg = f"Preshutdown event: code={control}, type={event_type}, data={data}"
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.hWaitStop)
            system_shutdown(with_error=False)
        elif control == win32service.SERVICE_CONTROL_POWEREVENT:
            msg = f"Power event: setting {data}"
        else:
            msg = f"Other event: code={control}, type={event_type}, data={data}"

        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            0xF000,  #  generic message
            (msg, ""),
        )

    def SvcStop(self):
        """Function that will be performed on 'service stop'.

        Removes the flag file to cause the main loop to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        system_shutdown(with_error=False)

    def SvcDoRun(self):
        """Function that will be performed on 'service start'.

        Starts the main function of the Registration Server"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        regserver.main.main()


def main():
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
