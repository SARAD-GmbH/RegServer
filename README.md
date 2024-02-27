# SARAD Registration Server Service

## Introduction ##

SARAD measuring instruments communicate via an UART over RS-232 or USB with a
propriatary protocol. The *SARAD Registration Server Service* has three functions:

1. On the side of the instrument (backend), it provides a network interface
   (frontend) for the communication with other *SARAD Registration Server
   Services* on remote locations.
2. On the side of the SARAD application software (frontend), it provides sockets
   and a REST-API to communicate with the application and on the other side
   (backend) a network interface for the communication with remote *SARAD
   Registration Server Services* or an USB interface for communication with
   locally connected instruments.
3. It provides frontends (Modbus, MQTT) to send measuring data from SARAD
   instruments to third party applications like monitoring systems from other
   vendors.

## Installation and usage ##


### Installation ###

#### For users ####
The *SARAD Registration Server Service* comes:

- Pre-installed on the appliances of the SARAD *Aranea* family of products.
  There is nothing to do for the user.
- As part of the installation of SARAD application software (*Radon Vision 8*, *dVision 4*).
  Just follow the hints in the Windows setup EXE of the respective application.

#### For developers ####
For test and development, the program is prepared to run in a virtual environment.

    git clone <bare_repository>

to clone the working directory from the git repository.

    cd RegServer
    pipenv install
    pipenv shell

to create the virtual environment, install all required dependencies and start
the shell within this virtual environment.

If you want to do further development and use modules that are only required
during the development or to make the documentation using SPHINX, use

    pipenv install --dev

### Configuration ###
In the configuration file `src\config.toml`, you can switch on or off the
various frontends and backends and set other parameters that will change the
functionality of the software. `doc\config.example.toml` is a commented version
of this configuration file containing all configurable parameters.

### Usage ###

Make sure that port 8008 is not used by any other application.

    cd src
    python sarad_registration_server.py

to start the program.

With a locally connected SARAD instrument or a *SARAD Registration Server
Service* running anywhere else in the same LAN, you should see log entries on
the command line indicating newly attached or disconnected SARAD instrument.

With your webbrower pointing to http://localhost:8008, you should see the
documentation of the REST-API. http://localhost:8008/list will provide a JSON
list of attached SARAD instruments with identification information like Family,
Type, Serial number.

### Documentation ###

#### General ####
Subdirectory `manual` contains the user manual.

The documentation of the implementation details is in subdirectory `doc`. It is
made with SPHINX (refer to https://www.sphinx-doc.org/en/master/). Run `make
html` in this directory to make the documentation from the source files.

#### In the SARAD intranet ####
Refer to http://http://intranet.hq.sarad.de/spc-sarad_network.pdf for the specification.

http://intranet.hq.sarad.de/regserver/html/index.html contains
a compiled HTML version of the documentation.
