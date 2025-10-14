import sys, time
from glob import glob
import serial

CPCL = open('ticket_test.lbl','rb').read()

def autodetect():
    # приоритет USB, затем BT, пропускаем входящий Bluetooth-порт
    for pat in ('/dev/cu.usb*','/dev/tty.usb*','/dev/cu.*'):
        for p in sorted(glob(pat)):
            if 'Bluetooth-Incoming-Port' in p: continue
            return p
    return None

port = sys.argv[1] if len(sys.argv)>1 else autodetect()
if not port:
    print("❌ Порт не найден. Укажи явно: python3 print_cpcl_mac.py /dev/cu.XXXXJ140701266")
    sys.exit(2)

print("🔎 Port:", port)
s = serial.Serial(port, baudrate=19200, timeout=1, write_timeout=3, rtscts=False, dsrdtr=False, xonxoff=False)
# лёгкая «раскачка»
s.write(b"\r\n"); s.flush(); time.sleep(0.05)
s.write(CPCL); s.flush()
time.sleep(0.1)
s.close()
print("✅ Sent CPCL")
