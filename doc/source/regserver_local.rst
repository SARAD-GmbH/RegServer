=========================================
Registration Server for local instruments
=========================================

Component diagram
=================

.. uml:: uml-c3_rslocal.puml

Instrument detection
====================

.. uml:: uml-instrument_detection.puml

Instrument removal
==================

.. uml:: uml-instrument_removal.puml

Reservation
===========

.. uml:: uml-reservation.puml

Binary messages
===============

.. uml:: uml-binary_messages.puml

Freeing the instrument
======================

.. uml:: uml-freeing.puml

Error case: Crashing SARAD App
==============================

.. uml:: uml-app_crash.puml

Error case: Interrupt USB connection
====================================

If the USB connection is unstable or disconnected during data transfer,
the instrument shall be regarded as disconnected.
In this case, the Cluster Actor has to kill the Device Actor.

.. uml:: uml-interrupt_usb.puml
