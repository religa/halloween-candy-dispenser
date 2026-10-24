"""One line for the operator: what works, how the evening is going, and the last thing that broke.

Details come only from exceptions and link/device messages, never from what visitors said."""

import time
from collections.abc import Callable

PARTS = ("arduino", "mic", "LLM", "ears", "voice")  # LLM: the Anthropic API that writes Hazel's replies
DETAIL_LIMIT = 80  # characters of an error kept on the line; the log has all of it
HEARTBEAT = 15 * 60.0  # s: the line is printed at least this often, so a quiet log still shows the program alive


class Status:
    def __init__(
        self,
        candies: Callable[[], int] = lambda: 0,
        write: Callable[[str], None] = print,
        parts: tuple[str, ...] = PARTS,
        clock: Callable[[], float] = time.time,
        distance: Callable[[], str] | None = None,
    ):
        """candies: the evening's count so far. parts: the ones this run uses, each starting OK.
        distance: the HC-SR04's reading now ("87 cm"), asked each time the line is printed; None
        leaves it off (no sensor this run)."""
        self.candies = candies
        self.distance = distance
        self.write = write
        self.clock = clock
        self.ok = dict.fromkeys(parts, True)
        self.visits = 0
        self.last_error: str | None = None
        self._shown = clock()  # when the line was last printed

    def set(self, part: str, ok: bool, detail: str = "") -> None:
        """Record a part working or not; the line is printed when that changes."""
        if part not in self.ok:
            return
        if not ok:
            self.last_error = f"{time.strftime('%H:%M', time.localtime(self.clock()))} {part}: {detail[:DETAIL_LIMIT]}"
        if self.ok[part] != ok:
            self.ok[part] = ok
            self.show()

    def visit(self) -> None:
        self.visits += 1

    def show(self) -> None:
        self._shown = self.clock()
        self.write(self.line())

    def beat(self) -> None:
        """Print the line if it hasn't been printed for HEARTBEAT s: call it often."""
        if self.clock() - self._shown >= HEARTBEAT:
            self.show()

    def line(self) -> str:
        fields = [f"{part} {'OK' if ok else 'LOST'}" for part, ok in self.ok.items()]
        if self.distance:
            fields.append(f"distance {self.distance()}")
        fields += [f"visits {self.visits}", f"candies {self.candies()}"]
        if self.last_error:
            fields.append(f"last error {self.last_error}")
        return "status: " + " · ".join(fields)
