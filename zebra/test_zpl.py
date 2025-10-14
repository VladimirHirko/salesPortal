import serial, time

PORT = "/dev/cu.XXXXJ140701266"
BAUD = 19200

zpl = "^XA\n^CF0,28\n^FO30,30^FDZPL TEST^FS\n^FO30,80^FDGranada RU 20/09^FS\n^FO30,130^FDSalesPortal^FS\n^XZ\n"
payload = zpl.replace("\r\n","\n").replace("\n","\r\n").encode("utf-8")

with serial.Serial(PORT, baudrate=BAUD, timeout=1, write_timeout=2,
                   rtscts=False, dsrdtr=False, xonxoff=False) as s:
    s.write(payload); s.flush()
    time.sleep(0.1)
print("ZPL sent")
