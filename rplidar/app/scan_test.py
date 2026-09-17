#!/usr/bin/env python3
"""Test RPLIDAR A1: UART3, MOTOCTL BCM27. No vehicle controls."""
import argparse
import json
import signal
import time
import math
from contextlib import nullcontext
from pathlib import Path
import serial
from gpiozero import PWMOutputDevice
from gpiozero.pins.lgpio import LGPIOFactory


def read_exact(port, n):
    data = bytearray()
    deadline = time.monotonic() + 3
    while len(data) < n and time.monotonic() < deadline:
        data.extend(port.read(n-len(data)))
    if len(data) != n:
        raise RuntimeError(f'Reponse incomplete: {data.hex(" ")} ({len(data)}/{n})')
    return bytes(data)


def descriptor(port, size, mode, kind):
    d = read_exact(port, 7)
    field = int.from_bytes(d[2:6], 'little')
    if d[:2] != b'\xa5\x5a' or field & 0x3fffffff != size or field >> 30 != mode or d[6] != kind:
        raise RuntimeError(f'Descripteur inattendu: {d.hex(" ")}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds', type=float, default=10, help='0 = continu jusqu a Ctrl+C')
    p.add_argument('--duty', type=float, default=0.6)
    p.add_argument('--output', default=str(Path(__file__).with_name('scans.jsonl')))
    args = p.parse_args()
    if not math.isfinite(args.seconds) or not math.isfinite(args.duty) or not (args.seconds == 0 or 1 <= args.seconds <= 120) or not 0 < args.duty <= 1:
        p.error('seconds: 0 (continu) ou 1..120; duty: 0..1 excluant zero')
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    motor = None
    port = None
    factory = LGPIOFactory(chip=0)
    count = 0
    try:
        port = serial.Serial('/dev/ttyAMA3', 115200, timeout=0.2, exclusive=True)
        motor = PWMOutputDevice(27, frequency=800, initial_value=0, pin_factory=factory)
        port.write(b'\xa5\x25')
        time.sleep(.2)
        port.reset_input_buffer()
        port.write(b'\xa5\x52')
        descriptor(port, 3, 0, 6)
        health = read_exact(port, 3)
        print('Etat:', health.hex(' '), flush=True)
        if health != b'\x00\x00\x00':
            raise RuntimeError('Etat lidar non OK')
        motor.value = args.duty
        print(f'Moteur: PWM 800 Hz, {args.duty:.0%}; stabilisation 2 s', flush=True)
        time.sleep(2)
        port.reset_input_buffer()
        port.write(b'\xa5\x20')
        descriptor(port, 5, 1, 0x81)
        deadline = time.monotonic() + args.seconds if args.seconds else float("inf")
        last_node = time.monotonic()
        buffer = bytearray()
        scan = []
        started = False
        scan_start = None
        rejected = 0
        latest = Path(__file__).with_name('latest.json')
        # Continuous mode writes one bounded snapshot; no growing log of scans.
        with (open(args.output, 'w') if args.seconds else nullcontext(None)) as out:
            while time.monotonic() < deadline:
                buffer.extend(port.read(max(1, min(port.in_waiting, 4096))))
                while len(buffer) >= 5:
                    b0,b1,b2,b3,b4 = buffer[:5]
                    angle = ((b1 >> 1) | (b2 << 7)) / 64
                    if (b0 & 1) == ((b0 >> 1) & 1) or not b1 & 1 or angle >= 360:
                        del buffer[0]
                        rejected += 1
                        continue
                    del buffer[:5]
                    last_node = time.monotonic()
                    if b0 & 1:
                        if started:
                            count += 1
                            valid = [r for r in scan if r['distance_mm'] > 0 and r['quality'] > 0]
                            duration = last_node-scan_start
                            record = {'timestamp': time.time(), 'duration_s': duration, 'points': scan}
                            payload = json.dumps(record)
                            temp = latest.with_suffix('.tmp')
                            temp.write_text(payload)
                            temp.replace(latest)
                            if out is not None:
                                out.write(payload+'\n')
                                out.flush()
                            nearest = min((r['distance_mm'] for r in valid), default=0)
                            if args.seconds or count % 20 == 0: print(f'Tour {count}: {len(scan)} points, {len(valid)} valides, {1/duration:.2f} Hz, minimum {nearest:.0f} mm', flush=True)
                        started = True
                        scan = []
                        scan_start = last_node
                    if started:
                        scan.append({'angle_deg': angle, 'distance_mm': (b3 | b4 << 8)/4, 'quality': b0 >> 2})
                if time.monotonic()-last_node > 2:
                    raise RuntimeError('Aucune mesure depuis 2 secondes')
        print(f'{count} tours complets enregistres dans {args.output}; octets rejetes: {rejected}', flush=True)
        if count == 0:
            raise RuntimeError('Aucun tour complet detecte')
    finally:
        try:
            if port is not None:
                try:
                    port.write(b'\xa5\x25')
                    port.flush()
                finally:
                    port.close()
        finally:
            if motor is not None:
                motor.off()
                motor.close()
            factory.close()
            print('Moteur lidar arrete.', flush=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Test interrompu.')
