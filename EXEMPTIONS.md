# Exemptions

The standing bar for publishing a generated integration is **three complete
fittings from three distinct GitHub accounts**. It exists because this
repository produces code that people install into Home Assistant, and one
person confirming their own capture is not independent evidence of anything.

Waiving that bar is the owner's call. Doing it quietly is not, which is why
this file exists.

The gate reads it:

```bash
.venv/bin/python verify/verify_wig.py --wig <slug> --integration <path> \
  --require-handles 3 --exemption EXEMPTIONS.md
```

With an entry matching the wig, the handle failure becomes a note that
quotes the reason into the build output, so the record travels with the
build. With no matching entry the gate still refuses. An entry covers one
wig and never generalizes to another.

Every entry carries the wig, the bar waived, the reason, who ruled it, the
date, and the condition that retires it. An exemption with no retirement
condition is a permanent lowering of the bar wearing a temporary name.

---

## sanmli-candles-th05

| | |
|---|---|
| **Bar waived** | Three distinct GitHub accounts. This wig has one. |
| **Ruled by** | David Bailey (@DAB-LABS), owner |
| **Date** | 2026-07-30 |
| **Retires when** | A second distinct GitHub account files a complete fitting on this wig. No further ruling needed; the exemption simply stops being load bearing and this entry should be deleted. |

**Reason.** This is the proof of concept. The whole point of the first
integration is to demonstrate that a wig can become a working, verified,
installable integration, and a proof of concept nobody can install proves
nothing. The bar exists to keep untested code from reaching people who
trusted the organization name rather than reading the source; it is not
meant to prevent the first artifact from existing.

**What this does not waive.** Everything else still applies and still
passed: forward, reverse and coverage all twelve of twelve, one signed
fitting that verifies against the current content hash, the send count held
against the send times the fitting recorded, and the README opening with
**untested by others** and naming the single fitter. A reader can see
exactly how thin the evidence is without reading this file.

**What it costs.** An integration published on one fitting is proven on one
person's hardware, in one room, with one blaster. It is entirely possible
that it works there and nowhere else. That is the risk the owner accepted,
and it is stated on the front of the repository rather than buried here.
