# The climate build path

Status: **three decisions open, no code written.** Everything below is
proposal. Nothing here is ruled.

An AC integration is not a bigger candle. The candle ships twelve codes and
a button each; an AC ships a lattice of up to 2,689 complete device states
and no buttons at all. Almost every assumption in the existing build steps
is about a codebook, and a lattice is not one.

Three questions decide the shape of everything else, and they should be
answered before any of it is written.

---

## 1. Does the lattice ship as data or as Python?

**Recommendation: data, in its own file, mirroring HAIR.**

HAIR already hit this wall and answered it. `matrix_store.py` keeps a
device's lattice at `hair/matrices/<device_id>.matrix.json` as
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

The counter-argument is real and worth stating: `codes.py` being Python is
what lets the gate import the generated module and check it directly, and
`WIG_ALIASES` is the provenance record that makes the codebook machine
checkable. A JSON lattice is not importable the same way.

That objection dissolves on inspection. The gate can read a data file
exactly as well; what it actually needs is a lattice it can compare against
the wig's, and JSON is a better shape for that than a Python literal, not a
worse one.

**If ruled:** the generated integration carries the lattice as its own
`hair-matrix/1`-compatible file and reads it at setup.

---

## 2. Who owns cell resolution?

**Recommendation: not the generated integration, and this is the important
one.**

When a user asks for cool / auto / 23, something has to decide which cell
transmits. HAIR's `wig_climate.resolve_cell` decides. If a generated
integration reimplements that logic, there are two algorithms answering one
question, and they will disagree eventually. That is the exact failure class
the row digest exists to prevent, one level up: a published contract with
two implementations does not fail loudly, it quietly decides that valid
things do not match.

Three ways out:

**a. Vendor `wig_climate.py`** into each generated integration, the way
`decoder.py` is vendored today. Honest and self-contained; each integration
owns its copy and the gate can check it. Cost: the copies drift, and unlike
a decoder, resolution is shared behaviour rather than per-device.

**b. Depend on a shared runtime package.** The `dab-labs-ir-codecs` idea,
promoted from a decoder library to a runtime that also carries resolution.
One implementation, versioned, and the integration declares it in
`requirements`. Cost: a real dependency for every AC integration, and a
release process for it.

**c. Reimplement and let the gate enforce agreement.** Cheapest to start,
and the gate can walk every cell. Cost: nothing stops the two drifting
between gate runs, and the gate is not run by the user.

**Preference: (b), and it changes what that package is for.** It was
deferred at roughly five integrations on the grounds that decoders were the
only shared thing. Resolution is a second shared thing and a more dangerous
one, because a decoder that drifts fails a check while a resolver that
drifts sends the wrong state to somebody's air conditioner.

**(a) is the acceptable interim** if the package is not worth standing up
for one integration. It should be chosen deliberately and written down,
not defaulted into.

---

## 3. What does the gate check for a stateful build?

**Recommendation: exhaustive lattice conformance, and it is the best check
in the whole repository.**

For a codebook the gate walks twelve aliases in both directions. For a
lattice it can walk every reachable state and confirm the generated
integration resolves each one to the same cell HAIR does. Two or three
thousand states, checked by machine, in seconds.

That is strictly stronger than anything available on the flat side, and it
is available precisely because the lattice is data. It answers the question
a human never could: does this integration land on the right state for
every combination a user can select, including the ones nobody will try
until next August.

Concretely, the check would assert:

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

## What is blocked, and on what

**No AC wig currently passes the input gate.** All six in the census fail on
data quality, and the fix is not here: it is somebody adopting one onto a
device, working the comb-flagged rows with a remote in hand, and saving it
back attested. Until one such wig exists, this path can be designed and
built but not proven, and building it against a wig that fails means the
first real test happens after the code is written.

**The three decisions above do not depend on that wig.** They can be ruled
now, and ruling them is what makes the work startable.

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
repository. The factory's response to a defective wig is to name the defect
and refuse.
