# verify/fixtures

Real wigs from the [Wig Shop](https://github.com/DAB-LABS/WigShop), copied
here unchanged so `test_gate.py` exercises the gate on files nobody built for
a test. Taken at WigShop `bdb71a2` (2026-09-16). The shop's wigs are CC0.

| File | Why it is here |
|---|---|
| `sanmli-candles-th05.wig.json` | RC5, signed, every label covers its capture. The clean case. |
| `dreo-fan-dr-haf004s-perfect-fit.wig.json` | Stored comb receipt says 0 suspects; HAIR 0.11 and later find 2. |
| `winix-fan-5500-perfect-fit.wig.json` | NEC through upstream decoders, whose frame accounting HAIR cannot verify. |

These are regression fixtures, not the shelf. If a shelf wig is later
superseded, these stay as they are: the point is that the gate's answer about
a given file does not move without somebody deciding it should.
