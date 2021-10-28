#!/usr/bin/env python3
"""Wrapper to start SARAD Instrument Server MQTT as Windows service"""
import multiprocessing
import socket
import sys

import servicemanager
import win32event
import win32service
import win32serviceutil

import registrationserver.ismqtt_main


class InstrumentServerMqtt(win32serviceutil.ServiceFramework):
    """Instrument Server MQTT service"""

    _svc_name_ = "InstrumentServerMqtt"
    _svc_display_name_ = "SARAD Instrument Server MQTT"
    _svc_description_ = (
        "Provides an MQTT interface to measuring instrument from SARAD GmbH "
        + "for remote control"
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        socket.setdefaulttimeout(60)

    def SvcStop(self):
        """Function that will be performed on 'service stop'.

        Removes the flag file to cause the main loop to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        registrationserver.ismqtt_main.set_file_flag(False)

    def SvcDoRun(self):
        """Function that will be performed on 'service start'.

        Starts the main function of the Instrument Server MQTT"""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        registrationserver.ismqtt_main.main()


if __name__ == "__main__":
    # Pyinstaller fix
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(InstrumentServerMqtt)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(InstrumentServerMqtt)
