"""Dispense candy from the computer: send 'd' to the Arduino over USB and print what it says.

Usage:
    uv run tools/dispense.py                  # finds the Uno's port by itself
    uv run tools/dispense.py --port /dev/ttyACM0   # Linux; /dev/cu.usbmodem14101 on macOS
    uv run tools/dispense.py --count 3        # three in a row over one connection

Opening the port restarts the Uno, so this waits for its "ready" line before sending.
Close the Arduino IDE's Serial Monitor first: only one program can hold the port.
The serial protocol lives in voice/dispenser.py.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # voice isn't an installed package

from voice.dispenser import Dispenser, DispenserError, Outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", help="serial port (default: the only Arduino port, /dev/cu.usbmodem* or /dev/ttyACM*)")
    parser.add_argument("--count", type=int, default=1, help="candies to dispense in a row over one connection")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")

    outcomes = []
    try:
        with Dispenser.open(args.port, on_line=print) as dispenser:
            for i in range(args.count):
                outcomes.append(dispenser.dispense())
                print(f"-> {outcomes[-1]} ({i + 1}/{args.count})")
                if outcomes[-1] is not Outcome.CANDY:
                    break
    except DispenserError as e:
        sys.exit(str(e))
    if any(o is not Outcome.CANDY for o in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
