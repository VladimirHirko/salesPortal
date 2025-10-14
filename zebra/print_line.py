import serial, time

PORT = "/dev/cu.XXXXJ140701266"  # подставь свой
BAUD = 19200

# Псевдочек для line_print — просто текст с переносами
ticket = """
==============================
  SalesPortal — Granada
  Date: 20/09/2025
  Hotel: Marbella Playa
  Pickup: 08:30 Reception
  Adults: 2   Children: 1
  Total: 160.00 EUR
------------------------------
  Booking code: SP-000123
==============================
Thank you and have a nice tour!
"""

with serial.Serial(PORT, baudrate=BAUD, timeout=1, write_timeout=2) as s:
    s.write(ticket.encode("ascii", "replace"))
    s.write(b"\n\n\n\n\n")  # несколько пустых строк для подачи бумаги
    s.flush()
print("Sent plain-text ticket to printer")
