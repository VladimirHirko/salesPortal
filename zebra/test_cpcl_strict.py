import serial, time

PORT = "/dev/cu.XXXXJ140701266"   # подставь свой
BAUD = 19200

cpcl = """! 0 200 200 320 1
TEXT 4 0 30 30 CPCL TEST
TEXT 4 0 30 80 Granada RU 20/09
TEXT 4 0 30 130 ---- SalesPortal ----
PRINT
"""

payload = cpcl.replace("\r\n","\n").replace("\n","\r\n").encode("utf-8")

with serial.Serial(
    PORT,
    baudrate=BAUD,
    timeout=1,
    write_timeout=2,
    rtscts=False, dsrdtr=False, xonxoff=False,  # всё вырубаем
) as s:
    # «разбудим»: небольшой мусор и пауза
    s.write(b"\r\n")
    s.flush(); time.sleep(0.15)

    # построчно с небольшими паузами — iMZ320 это любит
    for line in payload.split(b"\r\n"):
        if line:
            s.write(line + b"\r\n")
            s.flush()
            time.sleep(0.03)

    # завершающий CRLF
    s.write(b"\r\n")
    s.flush()

print("CPCL sent")
