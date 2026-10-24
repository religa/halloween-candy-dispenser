# Everyday commands. The full list (voice, tools) is in CLAUDE.md and docs/build-guide.md.

FQBN := arduino:avr:uno
# matches Serial.begin() in arduino/main.ino
BAUD := 115200
# the Uno: the only Linux or macOS USB serial port, unless given (make upload PORT=/dev/ttyACM1)
PORT ?= $(firstword $(wildcard /dev/ttyACM* /dev/ttyUSB* /dev/cu.usbmodem* /dev/cu.usbserial*))
# arduino-cli wants the sketch in a folder of its own name
SKETCH := out/firmware/main
UV := $(shell command -v uv)
# the systemd --user unit `make service` installs from tools/candy-witch.service
UNIT := $(HOME)/.config/systemd/user/candy-witch.service

.PHONY: help lint format test verify compile upload monitor start service stop logs

help:
	@echo "make lint      ruff: lint and check formatting"
	@echo "make format    ruff: fix lint and reformat"
	@echo "make test      geometry, voice and firmware tests (uv run pytest)"
	@echo "make verify    lint + test + compile the firmware"
	@echo "make compile   build arduino/main.ino for the Uno"
	@echo "make upload    compile and flash the Uno (PORT=$(PORT))"
	@echo "make monitor   print what the Uno says, each line timestamped (Ctrl-C to quit)"
	@echo "make start     run Hazel (voice/main.py) in this terminal, Ctrl-C to stop (ARGS=\"--text\" etc.)"
	@echo "make service   run Hazel under systemd --user for the evening, restarted if it stops"
	@echo "make stop      stop the service (before make start or make upload)"
	@echo "make logs      follow the service's output (Ctrl-C stops watching, not Hazel)"

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

verify: lint test compile

compile:
	@command -v arduino-cli >/dev/null || { echo "needs arduino-cli: https://arduino.github.io/arduino-cli/"; exit 1; }
	@arduino-cli core list | grep -q "^arduino:avr " || arduino-cli core install arduino:avr
	@mkdir -p $(SKETCH)
	cp arduino/main.ino $(SKETCH)/main.ino
	arduino-cli compile --fqbn $(FQBN) $(SKETCH)

# close the Serial Monitor, tools/dispense.py and voice/main.py first (systemctl --user stop
# candy-witch if `make service` runs it): one program per port
upload: compile
	@test -n "$(PORT)" || { echo "no Arduino found: plug it in, or pass PORT=..."; exit 1; }
	arduino-cli upload --fqbn $(FQBN) -p $(PORT) $(SKETCH)

monitor:
	@test -n "$(PORT)" || { echo "no Arduino found: plug it in, or pass PORT=..."; exit 1; }
	arduino-cli monitor -p $(PORT) -c baudrate=$(BAUD) --timestamp

# Hazel for the evening: installs the unit and (re)starts it; doesn't enable it at login
service:
	@test -n "$(UV)" || { echo "needs uv on the PATH: https://docs.astral.sh/uv/"; exit 1; }
	@mkdir -p $(dir $(UNIT))
	sed -e "s|@REPO@|$(CURDIR)|g" -e "s|@UV@|$(UV)|g" tools/candy-witch.service > $(UNIT)
	systemctl --user daemon-reload
	systemctl --user restart candy-witch
	@echo "logs: make logs · stop: make stop · start at login: systemctl --user enable candy-witch"

# Hazel in this terminal, for trying things: no restart if she exits
start:
	@! systemctl --user is-active --quiet candy-witch 2>/dev/null || { echo "the candy-witch service is running (it holds the Arduino's port): make stop first"; exit 1; }
	uv run --env-file .env voice/main.py $(ARGS)

stop:
	systemctl --user stop candy-witch

logs:
	journalctl --user -fu candy-witch
