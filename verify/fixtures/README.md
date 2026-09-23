# verify/fixtures

Real wigs from the [Wig Shop](https://github.com/DAB-LABS/WigShop), copied
here unchanged so `test_gate.py` exercises the gate on files nobody built for
a test. Taken at WigShop `bdb71a2` (2026-09-16). The shop's wigs are CC0.

| File | Why it is here |
|---|---|
| `sanmli-candles-th05.wig.json` | RC5, signed, every label covers its capture. The clean case. |
| `dreo-fan-dr-haf004s-perfect-fit.wig.json` | Stored comb receipt says 0 suspects; a live comb with current HAIR flags Oscillate Horizontal. |
| `winix-fan-5500-perfect-fit.wig.json` | NEC through upstream decoders, whose frame accounting HAIR cannot verify. |

These are regression fixtures, not the shelf. If a shelf wig is later
superseded, these stay as they are: the point is that the gate's answer about
a given file does not move without somebody deciding it should.

## climate/

`lattice.py` and `command.py` are frozen copies of the modules the Daikin
FTXS50KVM integration ships, so `test_climate.py` checks the climate gate
against real integration code rather than something written for the test. The
lattice they are run against is synthetic, built by the test from the candle's
codes: 2 modes, the Daikin's 5 fan speeds and 4 swing settings, 3
temperatures. If the Daikin integration's modules change, these do not, for
the same reason as the wigs above.
