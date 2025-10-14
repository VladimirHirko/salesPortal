#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Zebra iMZ320 — быстрый тест печати с macOS по Bluetooth/USB.
Автопоиск /dev/tty.* порта, установка 19200 бод, отправка CPCL.
Аргументы:
  --port /dev/tty.Zebra-IMZ320-SerialPort   # указать порт вручную
  --baud 19200                               # скорость (по умолчанию 19200)
  --text "Hello Zebra!"                      # текст для теста
  --file path/to/file.lbl                    # отправить CPCL из файла
  --dry-run                                  # показать, что будет отправлено, и выйти
"""

import sys, time, argparse
import serial
from serial.tools import list_ports

DEFAULT_BAUD = 19200

CPCL_TEMPLATE = """! 0 200 200 240 1
TEXT 4 0 30 30 SalesPortal Test
TEXT 4 0 30 70 {line1}
TEXT 4 0 30 110 Date: {date}
TEXT 4 0 30 150 OK: CPCL sent
PRINT
"""

def autodetect_port() -> str | None:
    """Ищем Zebra-подобные порты среди /dev/tty.*"""
    candidates = []
    for p in list_ports.comports():
        name = (p.device or "") + " " + (p.description or "") + " " + (p.manufacturer or "")
        name_l = name.lower()
        if "zebra" in name_l or "imz" in name_l or "mz" in name_l or "cpcl" in name_l:
            candidates.append(p.device)
    # если ничего «зебрового» не нашли — вернём первый tty.* в качестве подсказки
    if not candidates:
        for p in list_ports.comports():
            if "/tty." in (p.device or ""):
                candidates.append(p.device)
                break
    return candidates[0] if candidates else None

def send_cpcl(port: str, baud: int, payload: bytes) -> int:
    """Открываем порт, шлём, ждём и закрываем."""
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=2,
        write_timeout=5,
    )
    try:
        n = ser.write(payload)
        ser.flush()
        # Зебре иногда нужно мгновение, чтобы проснуться
        time.sleep(0.2)
        return n
    finally:
        ser.close()

def main():
    ap = argparse.ArgumentParser(description="Zebra iMZ320 CPCL test")
    ap.add_argument("--port", help="путь к порту, например /dev/tty.Zebra-IMZ320-SerialPort")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"скорость, по умолчанию {DEFAULT_BAUD}")
    ap.add_argument("--text", default="Hello Zebra!", help="строка для печати")
    ap.add_argument("--file", dest="cpcl_file", help="путь к CPCL-файлу (если указан — отправится он)")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что отправим, и выйти")
    args = ap.parse_args()

    port = args.port or autodetect_port()
    if not port:
        print("❌ Порт не найден. Включи принтер и Bluetooth, затем проверь: ls /dev/tty.*")
        sys.exit(2)

    if args.cpcl_file:
        with open(args.cpcl_file, "rb") as f:
            payload = f.read()
    else:
        from datetime import datetime
        cpcl = CPCL_TEMPLATE.format(line1=args.text, date=datetime.now().strftime("%Y-%m-%d %H:%M"))
        # Для надёжности переводим \n в \r\n (многие прошивки любят CRLF)
        cpcl = cpcl.replace("\r\n", "\n").replace("\n", "\r\n")
        payload = cpcl.encode("utf-8")

    print(f"🔎 Port: {port}")
    print(f"⚙️  Baud: {args.baud}")
    if args.dry_run:
        print("📝 CPCL to send:\n" + payload.decode("utf-8", errors="ignore"))
        return

    try:
        n = send_cpcl(port, args.baud, payload)
        print(f"✅ Отправлено {n} байт в принтер. Если тишина — проверь заряд/сон и имя порта.")
    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        if "Permission" in str(e):
            print("   Подсказка: попробуй временно через sudo или проверь права на устройство /dev/tty.*")
        sys.exit(1)

if __name__ == "__main__":
    main()
