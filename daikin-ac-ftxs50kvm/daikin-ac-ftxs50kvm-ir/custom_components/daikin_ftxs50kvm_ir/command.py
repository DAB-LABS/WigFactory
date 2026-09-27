"""A captured Pronto code, as the command an infrared emitter sends.

Home Assistant's ``infrared`` platform takes a ``Command`` whose raw timings
are signed microseconds, positive for a mark and negative for a space. The
lattice stores Pronto hex, so this converts one to the other, exactly the way
HAIR does, and adds the one thing a stored capture does not carry: a bounded
space at the end.

Why the end matters. Every capture in the lattice finishes on a 200 ms
silence, which is the remote's receiver timing out, not part of the message.
Left in, 16-bit emitters (Tuya and ZoSung blasters behind Zigbee2MQTT) reject
any value over 65,535 microseconds. Taken out entirely, the stream ends on a
mark, and Broadlink RM4 Pro firmware garbles a stream that ends on a mark.
HAIR settled this (its GH #98) with a 50 ms trailing space, added only at the
transmit boundary: it fits in 16 bits, it is longer than the gap between a
Daikin remote's two frames, and it is dead air to any receiver.

The upstream ``ProntoCommand`` only exists from infrared-protocols 8.x, which
Home Assistant installs on Python 3.14 only, so this does not depend on it.
WigFactory's gate checks that every cell converts here exactly as HAIR's own
``TerminatedCommand(ProntoCommand(code))`` does.
"""

from __future__ import annotations

from infrared_protocols.commands import Command

# Pronto word 0 for a learned, modulated code. The only kind in this lattice.
PRONTO_LEARNED = 0x0000
# Pronto encodes the carrier period as word[1] * 0.241246 microseconds.
PRONTO_FREQ_FACTOR = 0.241246
# The bounded trailing space every transmission ends on. See the docstring.
TERMINATOR_SPACE_US = 50_000


def pronto_timings(pronto: str) -> tuple[int, list[int]]:
    """Return (carrier Hz, signed microsecond timings) for a Pronto code.

    The timings end on a mark: a trailing space of any size is dropped here,
    as HAIR drops it, and the terminator is added by ``CellCommand``.
    """
    try:
        words = [int(word, 16) for word in pronto.split()]
    except ValueError as err:
        raise ValueError(f"not Pronto hex: {err}") from err
    if len(words) < 4:
        raise ValueError("Pronto code too short")
    if words[0] != PRONTO_LEARNED:
        raise ValueError(f"unsupported Pronto header {words[0]:04X}")
    if words[1] == 0:
        raise ValueError("Pronto frequency word is zero")

    period_us = words[1] * PRONTO_FREQ_FACTOR
    frequency = round(1_000_000 / period_us)
    pairs = words[2] + words[3]
    timing_words = words[4:]
    if len(timing_words) < pairs * 2:
        raise ValueError(
            f"Pronto code declares {pairs} pairs but carries "
            f"{len(timing_words)} timing words"
        )

    timings: list[int] = []
    for index in range(pairs):
        mark_us = round(timing_words[index * 2] * period_us)
        space_us = round(timing_words[index * 2 + 1] * period_us)
        timings.append(mark_us)
        if space_us > 0:
            timings.append(-space_us)
    if timings and timings[-1] < 0:
        timings.pop()
    return frequency, timings


def terminate(timings: list[int]) -> list[int]:
    """End a timing list on a bounded space, as HAIR's transmit boundary does."""
    out = list(timings)
    if not out:
        return out
    if out[-1] < 0:
        if -out[-1] > TERMINATOR_SPACE_US:
            out[-1] = -TERMINATOR_SPACE_US
        return out
    out.append(-TERMINATOR_SPACE_US)
    return out


class CellCommand(Command):
    """One lattice code, ready for an emitter, terminator included."""

    def __init__(self, pronto: str) -> None:
        """Convert the code once, up front, so a bad one fails at build."""
        frequency, timings = pronto_timings(pronto)
        super().__init__(modulation=frequency, repeat_count=0)
        self._timings = terminate(timings)

    def get_raw_timings(self) -> list[int]:
        """Signed microsecond timings, ending on the 50 ms terminator."""
        return list(self._timings)
