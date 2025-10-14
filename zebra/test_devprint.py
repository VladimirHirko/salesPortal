import serial, time
port = '/dev/cu.XXXXJ140701266'   # твой порт
baud = 19200

cpcl = """! 0 200 200 300 1
TEXT 4 0 30 40 SalesPortal DevPrint
TEXT 4 0 30 80 Granada RU 20/09
TEXT 4 0 30 120 ---- Test Line ----
PRINT
"""

# заменим \n на \r\n и добавим паузы
payload = cpcl.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8')

print("Opening port", port)
with serial.Serial(port, baudrate=baud, timeout=1, write_timeout=2) as s:
    for line in payload.split(b'\r\n'):
        if line.strip():
            s.write(line + b'\r\n')
            s.flush()
            time.sleep(0.05)     # короткая пауза между строками
    s.write(b'\r\n')
    s.flush()
print("Sent CPCL with CRLF and delays")
