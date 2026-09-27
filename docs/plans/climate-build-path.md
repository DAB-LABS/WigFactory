# The climate build path

Status: **built.** The three shape decisions were ruled on 2026-08-09. The
gate's climate checks and the first climate integration, the Daikin
FTXS50KVM in `daikin-ac-ftxs50kvm/`, were built against them in September
2026. `AGENTS.md` section 5.1 is the working guide; this page is why.

An AC integration is not a bigger candle. The candle ships twelve codes and
a button each; an AC ships a lattice of up to 2,689 complete device states
and no buttons at all. Almost every assumption in the existing build steps
is about a codebook, and a lattice is not one.

Three questions decided the shape of everything else. All three now have
answers, and the sections below record what was ruled and why, so that
whoever writes the code is not re-litigating it.

---

## 1. Does the lattice ship as data or as Python?

**RULED: data. One file of codes.** (Owner, 2026-08-06.)

HAIR had already hit this wall and answered it the same way. `matrix_store.py`
keeps a device's lattice at `hair/matrices/<device_id>.matrix.json` as
`hair-matrix/1`, explicitly because the census worst case is a 7.9 MB
Mitsubishi with 2,689 cells and rewriting that on every device rename was
unacceptable. The same numbers apply to a generated integration for worse
reasons:

- A 2,689-entry Python literal is not source anybody reviews. It is a
  database with a `.py` extension.
- It would go through ruff on every CI run, and through hassfest, and
  through the HACS action.
- Home Assistant would parse it at import time, on the event loop, on every
  restart.

The counter-argument was real and worth recording: `codes.py` being Python is
what lets the gate import the generated module and check it directly, and
`WIG_ALIASES` is the provenance record that makes the codebook machine
checkable. A JSON lattice is not importable the same way.

That objection dissolves on inspection. The gate can read a data file exactly
as well; what it actually needs is a lattice it can compare against the wig's,
and JSON is a better shape for that than a Python literal, not a worse one.

**What this means for the build:** the generated integration carries the
lattice as its own `hair-matrix/1`-compatible file and reads it at setup. The
Python beside it holds behaviour, not codes.

---

## 2. Who owns cell resolution?

**RULED: vendor `wig_climate.py`, and the shared package is not being stood
up for this.** (Owner, 2026-08-06.)

When a user asks for cool / auto / 23, something has to decide which cell
transmits. HAIR's `wig_climate.resolve_cell` decides. If a generated
integration reimplements that logic, there are two algorithms answering one
question, and they will disagree eventually. That is the exact failure class
the row digest exists to prevent, one level up: a published contract with two
implementations does not fail loudly, it quietly decides that valid things do
not match.

So reimplementation was off the table, and the live choice was between
vendoring HAIR's module and depending on a shared runtime package. The ruling
is vendoring, which is the same arrangement `decoder.py` already has: each
integration owns a copy, the copy is checked against HAIR by the gate, and no
integration acquires a runtime dependency on a package that does not exist
yet.

**The cost this accepts, written down so nobody is surprised by it.** Copies
drift, and a resolver is not a decoder. A decoder that drifts fails a check;
a resolver that drifts sends the wrong state to somebody's air conditioner.
Vendoring is therefore only safe while the gate genuinely proves agreement,
which makes section 3 load bearing rather than nice to have.

The shared package (`dab-labs-ir-codecs`) remains deferred rather than
rejected. It was deferred at roughly five integrations when decoders were the
only shared thing; resolution is a second and more dangerous one, so the
number that triggers the conversation is now lower than it was, not higher.

---

## 3. What does the gate check for a stateful build?

**Exhaustive lattice conformance, and it is the best check available
anywhere in this repository.**

For a codebook the gate walks twelve aliases in both directions. For a
lattice it can walk every reachable state and confirm the generated
integration resolves each one to the same cell HAIR does. Two or three
thousand states, checked by machine, in seconds.

That is strictly stronger than anything available on the flat side, and it is
available precisely because the lattice is data. It answers the question a
human never could: does this integration land on the right state for every
combination a user can select, including the ones nobody will try until next
August.

Concretely, the check asserts:

- Every state the entity advertises resolves to exactly one cell.
- Every resolution agrees with `wig_climate.resolve_cell`.
- Every cell the lattice contains is reachable from some advertised state,
  and every advertised state reaches a cell. A cell nobody can select is
  dead weight; a state that resolves to nothing is a control that does
  nothing.
- Collapsed rows are advertised as collapsed. Where a device ignores
  temperature, the entity must not offer a temperature control in that
  combination. This is the row-collapse rule the comb already knows, and
  getting it wrong is a control that silently does nothing.
- The unit is honoured. A Fahrenheit lattice read as Celsius is a silent
  thirty degree error.

---

## 4. What a matrix wig has to carry before it can be built

**RULED: the shop's rule is the factory's rule. Every row of the derived
checklist must be claimed as working.** (Owner, 2026-08-09.)

Nobody fits 2,689 cells. HAIR's `dimension_checklist` derives a short
deterministic walk over the lattice, twelve to twenty rows, that exercises
each dimension rather than each state. A claim on a matrix wig attests that
walk.

The factory now derives the same checklist from the lattice and requires
every digest in it to appear as a `worked` row in one bundle. It reads that
requirement out of HAIR rather than restating it, and it compares
`expected <= worked` exactly as the shop does.

This closes a hole the factory had inherited. `bundle_is_complete` compares a
bundle against the rows the bundle itself carries, so a one-row bundle over a
2,700-cell lattice read as a complete fitting. The checklist is derived from
the lattice instead, which is the thing the claim is supposed to be about.

Where the shop's rule moves, this moves with it. The factory is deliberately
not the place that decides how much of a lattice a person has to vouch for.

---

## What is blocked, and on what

**Nothing, on the input side, since 2026-09-16.** The Daikin FTXS50KVM
(`daikin-ac-ftxs50kvm-perfect-fit.wig.json`) is the first AC wig to pass the
input gate: physically captured off an ARC433B70 remote, a complete lattice
of 2 modes, 5 fan speeds, 4 swing settings and 13 temperatures (520 cells,
one frame shape throughout), one Perfect Fit, no comb suspects, and HAIR's
DAIKIN216 field map read every field of every code with no mismatch. It is
the wig this path gets built and proven against.

Before it, all six AC wigs in the census failed on data quality, and the fix
was never going to be here: it was somebody adopting one onto a device,
working the flagged codes with a remote in hand, and saving it back.

**The kind-to-platform table already says `ac`, `heater` -> `climate`.** No
change needed there.

---

## What this deliberately does not propose

**A derivation or reconciliation engine.** An earlier draft of this proposed
that the factory derive a field-level encoder per device, regenerate the
lattice, and reconcile it against the import. That was wrong twice over:
HAIR has it planned as its own release, carrying the checksum-learning
research risk, and building a second one here would be the same
two-implementations mistake as section 2. If a derivation engine happens, it
happens in HAIR and the factory consumes its output like any other wig.

**Repair of any kind.** Combing never changes a code and neither does this
repository. Anomalies the comb finds are surfaced on the device as individual
commands, to be tested or replaced there and then attested. The factory's
response to a defective wig is to name the defect and refuse.
