"""LED at Raspberry Pi's GPIO pin 23 shall blink until the system time is
synchronized."""
import select
import sys

from gpiozero import LED
from systemd import journal

led = LED(23)
led.blink()

j = journal.Reader()
j.log_level(journal.LOG_INFO)

j.seek_tail()
j.get_previous()

p = select.poll()
p.register(j, j.get_events())

while p.poll():
    if j.process() != journal.APPEND:
        continue
    for entry in j:
        if "System Time Synchronized" in entry["MESSAGE"]:
            sys.exit()
