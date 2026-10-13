# WigFactory: the runbook

You are a coding agent working in this repository. Your job is to turn one
**wig** into one installable Home Assistant integration.

This file is the procedure: what to run, in what order, what counts as
passing, and who decides. The reasons behind each rule, and the history that
produced them, are in [`docs/background.md`](docs/background.md). Read that
before you change a rule here. You do not need it to follow one.

**Work through the stages in order. Do not skip ahead.** Stage 5 is a gate:
if it does not pass, you do not continue to stage 6, and you do not publish
anything. That gate is the reason this repository exists.

| Stage | Run | Passes when | Who decides |
|---|---|---|---|
| [1. Set up](#1-set-up) | `./setup.sh` | `.venv` exists on Python 3.13 or later and every reference cloned | nobody: it works or it says why |
| [2. Survey the shelf](#2-survey-the-shelf) | `verify/survey_shop.py` | always, it is a report | **the owner** picks the wig |
| [3. Gate the wig](#3-gate-the-wig) | `verify/verify_wig.py --wig <slug> --gate-only` | exit 0 | the gate; a refusal is final here |
| [4. Build](#4-build) | this file, sections 4.1 to 4.4 | the tree mirrors the reference | you |
| [5. Verify](#5-verify) | `verify/verify_wig.py --wig <slug> --integration <path>` | exit 0 | the gate, then **the owner** on a bench check |
| [6. Publish](#6-publish) | `publish/publish_integration.py`, dry run then `--publish` | the dry run reads right and the tool's own gate passes | **the owner**, every time |
| [7. Maintain](#7-maintain) | `publish/update_integration.py` | the pull request's checks pass | **the owner** merges, unless they have said otherwise |

**Exit codes, everywhere under `verify/`:** 0 passed, 1 refused (something
is wrong with the wig or the integration), 3 no verdict (HAIR missing or too
old, a dependency not installed, or the gate itself crashed). A 3 is never a
statement about a wig. The survey exits 0 once it has produced a survey,
whatever is on the shelf.

**Always run the scripts through `.venv/bin/python`.** They are not marked
executable on purpose ([why](docs/background.md#set-up)).

---

## 0. Ground rules

These apply to everything you write here.

1. **`reference/` is read only.** It holds shallow clones of other
   repositories, and `setup.sh` is the only thing that writes there. Read
   them, mirror their structure, never edit them, never commit them.

   The Wig Shop clone lives there too, and a wig is input rather than an
   example, so it gets one extra rule: **copy the wig you are building from
   into `wigs/` and work on the copy.** The clone stays pristine, `setup.sh`
   stays free to hard reset it, and the distinction between "somebody else's
   repository" and "my working input" stays legible.
2. **Mirror the reference exactly.** When you build the integration, match
   `lg_infrared`'s folder layout, file names and file responsibilities. Do
   not invent a nicer structure. The point of a factory is that every
   product comes out the same shape.
3. **Read the references fresh at build time.** The `infrared` platform is
   young and its contract still moves. `lg_infrared` was broken once by a
   change from Timing objects to flat integers (home-assistant/core#172209).
   Generate against what is in `reference/` today, not against what you
   remember.
4. **Tests never need real hardware.** Everything is timings in and timings
   out. If a test wants a blaster, the test is wrong.
5. **Codecs are written from protocol specifications only.** No code derived
   from GPL or LGPL implementations: not IRremoteESP8266, not ESPHome's C++,
   not LIRC. Timing constants are protocol facts and are fine. Code
   structure is not. This keeps the eventual donation to
   `infrared-protocols` unencumbered, and it is not negotiable.
6. **Public text has a house style.** No em dashes anywhere. No AI tells: no
   rows of check marks, no emoji sprays, no "delve", no breathless summary
   paragraphs. Never name an AI vendor or assistant product in a README, a
   code comment, a commit message or an issue. Write like a person who built
   the thing.
7. **Never key identity on an entity_id.** `lg_infrared` shipped a config
   entry whose unique_id was derived from the infrared entity_id and had to
   walk it back with a migration. Learn it here for free.
8. **Ask before publishing.** Stages 1 through 5 are yours, and you build
   only what the owner picked at stage 2. Stage 6 pushes to a public
   organization under the owner's name, and the owner rules on it.

---

## 1. Set up

```bash
./setup.sh
```

**Passes when** it finishes: a `.venv` on the newest Python 3.13 or later it
can find, with `verify/requirements.txt` installed, and these shallow clones
in `reference/`:

| Path | What it is | Why you need it |
|---|---|---|
| `reference/HAIR` | The HAIR integration, at the release in `verify/HAIR_REF` | Its decoders are the independent witness in stage 5, and `wig_format.py` is the input parser |
| `reference/WigShop` | The Wig Shop | Where wigs come from. The factory reads the merged file everybody else sees, not somebody's local export |
| `reference/home-assistant-core` | Home Assistant core, `dev`, sparse | `homeassistant/components/lg_infrared` is the target output shape; `homeassistant/components/infrared` is the platform contract |
| `reference/infrared-protocols` | The upstream codec library | Tells you which protocols upstream can already encode and decode, and what a module that graduates upstream has to look like |
| `reference/integration_blueprint` | ludeeus's HACS scaffold | Repository level furniture: workflows, `hacs.json`, gitignore |

**3.13 is a hard floor**, matching HAIR's own `requires-python`. If setup
reports no suitable interpreter, install one and run it again; it will not
guess and it will not silently skip the gate. **Upstream
`infrared-protocols` is required**, and the gate refuses to start without it
rather than call a good NEC wig undecodable
([why](docs/background.md#set-up)).

**When to run it.** `setup.sh` never runs itself. You run it, it fetches and
hard resets every clone to its remote, and the clones then sit still until
you run it again. **Run it at the start of a build, and again before any
build whose output you intend to publish.**

---

## 2. Survey the shelf

```bash
.venv/bin/python verify/survey_shop.py              # a table
.venv/bin/python verify/survey_shop.py --markdown   # the same, as the shelf report renders it
```

The same report runs weekly in the `Shelf report` workflow, and on demand
from the Actions tab, and lands in that run's summary. It runs the input
gate over every wig in the shop and sorts the results:

| Bucket | Meaning | What happens next |
|---|---|---|
| READY | passes every check and has no integration yet | a candidate for the owner |
| BUILT | an integration for it already lives here | stage 7 if its wig moved |
| DEFECTS | the wig's own codes contradict themselves: a lattice hole, a truncated frame, two temperatures sharing one payload | fixed at the shop or in HAIR, never here |
| UNSUPPORTED | may be perfectly good, but uses something the factory cannot build or check yet | waits for the factory |
| UNUSABLE | will not parse, or nothing on it vouches for the codes (no Perfect Fit) | waits for somebody to fit it, at the source |

Every criterion is something the gate already computes, so nothing here is
judgement. DEFECTS is the bucket worth reading: the gate found something
wrong with the codes rather than with the paperwork. **The listing is the
proposal. The owner picks. Do not build anything before they have picked.**

It also says, as a notice, when a newer HAIR release exists than the pin.

---

## 3. Gate the wig

```bash
# by shop slug, resolved from reference/WigShop and stamped with its commit
.venv/bin/python verify/verify_wig.py --wig sanmli-candles-th05 --gate-only

# or by path, for a wig that is not in the shop
.venv/bin/python verify/verify_wig.py --wig wigs/whatever.wig.json --gate-only
```

**Prefer the slug.** It records the shop commit, which makes the fitting
evidence reproducible later; a path records nothing
([why](docs/background.md#why-the-slug-not-the-path)). Run the gate before
you look at anything else.

**Passes when** it exits 0. Every requirement below is a refusal, not a
warning:

1. **It parses** through HAIR's own `wig_format.parse_wig`. Not a lookalike
   parser you wrote. The same code the user's install runs on import.
2. **It carries at least one complete claims bundle**, a Perfect Fit: one
   person claimed every row worked. A wig with no fitting is a spreadsheet,
   and this factory does not take spreadsheets.
3. **Every bundle names this wig.** Its `wig_id` has to match the wig's. A
   bundle naming another wig is not a stale attestation, it is somebody
   else's, and row digests can still line up by coincidence on a shared code
   set.
4. **Signatures verify** where a bundle carries `key` and `sig`. A bundle
   that claims a signature and fails it is a hard stop. An unsigned bundle
   passes with a note.
5. **Every signal decodes, and to one protocol family.** Mixed protocol wigs
   are out of scope: one wig, one codec. A signal that will not decode at
   all is out of scope too, because there is nothing to generate from raw
   replay.
6. **Every label accounts for its whole capture.** A codebook rebuilds each
   code from its decoded label, so a label that explains only part of what
   was captured means the integration would transmit something nobody
   fitted. HAIR 0.14.2 answers this per signal. `False` refuses. `None`
   means HAIR cannot say, usually because the decoder is upstream's, and
   that notes and does not refuse (owner ruling 2026-09-22); the forward and
   reverse checks still have to pass.
7. **No carrierless codes.** A Pronto with a `0100` header must go out
   unmodulated. Until it is established that a generated integration can
   send one that way, the gate refuses rather than ship a code that would go
   out modulated and look like it worked.
8. **No extra lattices yet.** A `hair-wig/4` matrix carries peer lattices
   for presets. Every lattice check here reads the main lattice only, so
   those codes would pass unchecked, and the gate refuses until it checks
   them too.
9. **No climate cell lands on the wrong state unanswered.** When the live
   comb says a cell sends a state other than the one on its label
   (`field-mismatch`, `duplicated-neighbour`), that refuses unless a
   person's answer to that cell still stands against its current bytes
   (owner ruling 2026-09-23). Command wigs only get a note.
10. **No row asks for a waveform that cannot exist.** Setting both
    `bypass_protocol` and a ditto count is a contradiction: only the encoder
    renders a repeat frame, so a bypassed row asking for one describes
    something nothing can produce.
11. **The integration reproduces the transmit recipe**, when one is being
    checked. See stage 5.
12. **A matrix wig's lattice holds together** (below).

### On a matrix wig

A matrix wig carries a climate block, a lattice of cells, one per complete
device state. The gate checks the lattice against itself
([why](docs/background.md#matrix-wigs)):

- **Complete, mode by mode.** Each mode is judged within its own settings,
  as HAIR's comb judges it: every fan the mode uses, with every swing the
  mode uses, must have a row, and every row in the mode must carry the same
  unbroken run of temperatures. A mode with fewer settings passes, and the
  integration offers only what that mode has. A hole inside a mode, a gap in
  a temperature run, or a mode the lattice declares and never fills refuses.
- **Collapsed rows pass.** A row where every temperature sends one code
  means the device ignores temperature there. The integration must not offer
  a temperature control in those combinations.
- **Partial collapse refuses.** If a row varies with temperature at most
  settings and then two adjacent values collide, one of them transmits the
  wrong state.
- **Frame shape.** Every cell of one device sends the same protocol, so
  every cell should have the same frames of the same lengths. A short frame
  is a truncated capture and refuses. A stray burst after the last frame is
  capture noise and only notes.
- **Celsius is asserted, not assumed.** The format carries a `unit`, and the
  gate reads it.

Fittings on a matrix wig attest the **dimension checklist**, a deterministic
12 to 20 row walk, not the whole lattice. That is HAIR's definition and the
gate reads it from HAIR rather than reimplementing it.

### What the gate also reports, and never enforces

- **The live comb.** The gate combs every wig itself, with the pinned HAIR,
  on every run. A comb receipt stored in a wig is read, reported and
  compared, and never taken as the answer. The live comb reports; its only
  refusal is requirement 9. Answers count per cell, as HAIR's Detangle
  counts them, so an answer on one cell never settles its neighbour ([the
  three layers](docs/background.md#the-comb-run-live)).
- **Repairs and attestations**, counted, carried into the README, and never
  treated as evidence.
- **Distinct contributors.** The gate counts GitHub accounts in canonical
  form, and says out loud when two fittings collapse to one person. A
  display handle never counts. **There is no promotion bar:** the number
  goes to the owner at stage 6, and the owner decides what it is worth
  ([why](docs/background.md#counting-people-not-strings)).
  `--require-handles N` still exists for anybody who wants a hard floor on a
  particular run. It is off by default and CI does not pass it.
- **Pooled coverage**, which is a different number from the account count.
  Print both; never substitute one for the other.

### When it passes

**Record what the gate printed.** The wig id, content hash, shop commit,
fitter handles and dates, HAIR version, send count and pooled coverage go
into the generated README in stage 4.4, and you cannot reconstruct them
later.

Then copy the wig into `wigs/` per ground rule 1 and work from that copy.

### When it refuses

**Stop and report why.** Do not repair the wig. Corrections are the fitter's
job, in HAIR, on the device: adopt it, fix it there, save it back to the
closet
([why](docs/background.md#where-a-wig-comes-from-and-why-the-factory-never-repairs-one)).
In particular, never edit a `github` value to make a count come out better:
the signature covers it, and rewriting it forges somebody's attestation.

Expect refusals. The shelf takes wigs with no fitting at all, and this
factory builds nothing short of a Perfect Fit ([what the shop
guarantees](docs/background.md#what-the-wig-shop-guarantees-and-what-it-does-not)).

---

## 4. Build

### 4.1 Decide what you are building, and name it

**Protocol.** The gate already told you. Check
`reference/infrared-protocols` for the matching command class and note
precisely what it can do. As of this writing `RC5Command` can encode and
cannot decode, which matters in 4.2.

**Kind.** Read the wig's `kind` field. A wig with a climate block is a
climate integration (4.3). Otherwise kind decides which device class wrapper
you generate alongside the buttons:

| kind | wrapper platform |
|---|---|
| `tv`, `settopbox`, `projector`, `soundbar`, `receiver` | `media_player` |
| `light`, `candles` | `light` |
| `fan` | `fan` |
| `ac`, `heater` | `climate` |
| `blinds`, `screen` | `cover` |
| anything else, or absent | buttons only, and say so in the README |

Buttons are always generated, one per signal. The wrapper is additional. A
kind that is not in this table and plainly wants a wrapper (a fireplace,
say) is the owner's call before you build, not yours.

**Naming.** Ruled and not open for redesign
([why](docs/background.md#names)):

- Repository: `<brand>-<kind>-<model>-ir`, lowercase kebab, `kind` squashed
  to one word with no inner dashes. It is the wig's stem plus `-ir`.
- Domain: `<brand>_<model>_ir`, lowercase snake. Per device, not per brand.
  The `-ir` names the medium and goes in the domain too.
- Pieces drop out when genuinely absent. Fall back to the wig's name slug
  when almost nothing is known.
- **The tier suffix is stripped.** HAIR names a download
  `<brand>-<kind>-<model>-perfect-fit.wig.json`, and
  `fable-fan-ft-9000-perfect-fit.wig.json` publishes as
  `fable-fan-ft-9000-ir`. `verify_wig.device_stem` owns the stripping and
  `TIER_SUFFIXES` owns the list. Either spelling resolves a wig on the
  command line.
- **The `<kind>` is HAIR's word, not the file's,** through HAIR's own
  `normalize_kind`: a Komeco AC filed as `airconditioner` still becomes
  `komeco-ac-...-ir`. The publish tool still names from the filename stem
  and does not yet apply this, so **if the wig's filename spells kind
  differently from HAIR's list word, stop and raise it** before publishing.
- **Lowercase**, slug and domain both.
- **Identity fields feed labels, never identifiers.** The wig's `brand`,
  `model`, `kind` and `name` carry real human casing and are the right
  source for every human-facing string: the `name` in `manifest.json` and
  `hacs.json`, the README heading, the repository description, the topics.
  They are the wrong source for the slug, the domain or the folder.

**Get the domain right before the first publish.** After that it is
permanent.

### 4.2 A codebook integration

**The codebook table.** Derive it mechanically from the decoded identities,
never by hand and never by pattern matching on aliases:

- One entry per signal, keyed on the wig's alias verbatim.
- The value is the decoded command. The decoded address is one module level
  constant, and every signal must share it. If they do not, the wig is two
  devices and stage 3 should have caught it.
- **Press state is excluded.** The RC-5 toggle bit never enters the
  codebook. The integration flips it per press instead, exactly as HAIR
  does.

**The contract the gate reads.** `verify/verify_wig.py` already implements
the gate. Your job is to satisfy its contract, which is what makes the
generated `codes.py` machine checkable:

```python
PROTOCOL = "RC5"
ADDRESS = 0x1F

class SanmliTh05Code(IntEnum):
    ON = 0x01
    FLICKER = 0x02
    ...
    def to_command(self, *, toggle: int = 0, repeat_count: int = 0) -> Command:
        ...

WIG_ALIASES: dict[str, SanmliTh05Code] = {
    "On": SanmliTh05Code.ON,
    "FL": SanmliTh05Code.FLICKER,
    ...
}
```

`WIG_ALIASES` maps the wig's alias, verbatim, to the enum member generated
from it. It is the provenance link and the gate reads it. Keep it.

`WIG_RECIPE` sits beside it, mapping the wig's alias verbatim to
`(send_count, ditto_count, bypass_protocol)`. It is optional only while
every row is plain, meaning a send count and nothing else, because
`DEFAULT_SEND_COUNT` already covers that case on its own. The moment one row
asks for a ditto or a bypass, the map is mandatory and a missing one is a
refusal.

**The tree.** Mirror
`reference/home-assistant-core/homeassistant/components/lg_infrared` for the
integration, and `reference/integration_blueprint` for the repository
furniture around it:

```
<device>/
  <brand>-<kind>-<model>-ir/
    custom_components/<domain>/
      __init__.py          forward the platforms, set up and unload the entry
      codes.py             the codebook, plus WIG_ALIASES and WIG_RECIPE
      const.py             DOMAIN and configuration keys
      config_flow.py       emitter EntitySelector, optional receiver EntitySelector
      entity.py            base entity setting DeviceInfo, plus the platform mixins
      button.py            one button per code
      <wrapper>.py         the device class wrapper chosen in 4.1
      event.py             receiver side, when a decoder is vendored
      decoder.py           the vendored RX decoder, when upstream cannot decode
      manifest.json
      translations/en.json
      brand/icon.png
    hacs.json
    README.md
    LICENSE
    .github/workflows/lint.yml
    .github/workflows/validate.yml
    .gitignore
```

The details that are not obvious
([why](docs/background.md#codebook-integrations)):

- **`manifest.json`** carries `"dependencies": ["infrared"]`, `"iot_class":
  "assumed_state"`, `"integration_type": "device"`, `"config_flow": true`,
  `"version"`, and `"codeowners"`.
- **Entities do the IR work through the platform's mixins.**
  `InfraredEmitterConsumerEntity` provides `_send_command`.
  `InfraredReceiverConsumerEntity` provides the `_handle_signal`
  subscription. Read them in `reference/home-assistant-core` rather than
  reimplementing them.
- **The config flow** uses an EntitySelector for the emitter and an
  **optional** EntitySelector for the receiver.
- **`event.py`** decodes an incoming signal, matches it against the
  codebook, and fires an HA event. It must carry an `unknown` fallback so
  that a code outside the enum never raises, and it must tolerate both
  timing shapes (Timing objects with `.high_us` and `.low_us`, and flat
  integers). Copy the posture from HAIR's `event_parser.py`.
- **`decoder.py`** exists only when upstream cannot decode the protocol.
  Adapt it from HAIR's `custom_components/hair/decoders/`, which is written
  from specifications and licensed cleanly for exactly this. Keep the
  upstream shape: a classmethod `from_raw_timings(timings: list[int]) ->
  Self | None`, signed microseconds with positive marks and negative spaces,
  bounds checked indexing so it never raises on malformed input.
- **RC-5 press state on transmit.** One toggle value per config entry, mod
  2, flipped after each send in which at least one emitter accepted the
  command. Not per entity, not per button.
- **Frames per press comes from the wig, not from you.**
  - `const.py` carries `DEFAULT_SEND_COUNT`, `MIN_SEND_COUNT = 1`,
    `MAX_SEND_COUNT = 10` and a gap between frames of about 100ms.
  - `DEFAULT_SEND_COUNT` is the **highest `send_count` the wig states**,
    which is the number the gate prints. Not a number you chose. The gate
    refuses a default below it.
  - All the frames in one press share one RC-5 toggle value, and the toggle
    advances once, after the last of them.
  - Expose it in the options flow. This is the ONLY one of the three recipe
    fields that is the user's to change.
  - **The ditto is not this.** `ditto_count` is rendered by the encoder
    inside a single transmission, it is in the digest, and it is not
    tunable. Carry it into the command's `repeat_count` and declare it in
    `WIG_RECIPE`.
  - **When rows disagree** on send count, a single knob cannot express it.
    Ship the highest, and say in the README which rows wanted less. The gate
    prints the spread.
- **Requirements are PyPI specifiers only.** Never a VCS URL. Never a space
  around the `@` in a requirement string either.

Write tests alongside. Round trip every codebook entry through encode and
decode, assert the vendored decoder agrees with HAIR on every wig signal,
and mock every connection.

### 4.3 A climate integration

A matrix wig does not become a codebook. There is nothing to encode: every
state the unit can be in was captured as a complete code, and the
integration replays the one that matches ([the
rulings](docs/plans/climate-build-path.md)).

```
custom_components/<domain>/
  __init__.py        loads the lattice in the executor, forwards CLIMATE
  lattice.json       the wig's climate block, unchanged, as hair-matrix/1
  lattice.py         loads it, and resolves a state to a cell (no HA imports)
  command.py         Pronto to signed timings, plus the terminator (no HA imports)
  climate.py         one ClimateEntity, RestoreEntity, assumed state
  config_flow.py     emitter, sends per change, options flow for the latter
  const.py, entity.py, manifest.json, translations/en.json, brand/
```

To see how a device packs its state before you decide what the entity
exposes, run the microscope:

```bash
.venv/bin/python verify/derive_fields.py --wig wigs/<file>.wig.json
```

It lines up every cell, finds the bit positions that move, groups them into
runs and says which dimension each run tracks. It is not a check and it
never refuses. The judgement is still yours: deciding a four bit run really
is temperature, recognising a checksum, choosing what the entity exposes.

The details that are not obvious
([why](docs/background.md#climate-integrations)):

- **`lattice.json` is copied, never rebuilt.** `{"format": "hair-matrix/1",
  "wig": {..., "wig_id": ...}, "climate": <the wig's climate block>}`. The
  gate compares the climate block to the wig's field for field and refuses
  any difference. One cell per line keeps a diff readable.
- **Resolution is HAIR's, vendored.** `lattice.py` carries a trimmed copy of
  `wig_climate.resolve_cell` and a `Resolver.resolve(hvac_mode, fan_mode,
  swing_mode, temperature)` that the entity calls for every send. The gate
  calls the same method for every state the entity offers, plus off-grid and
  out-of-range temperatures, and requires HAIR's answer every time.
- **When modes differ, the entity offers per mode.** If the wig's modes
  carry different fans, swings or temperatures (a dry mode with one fan
  speed), `Resolver.offers(hvac_mode)` must return what that mode has, as
  `{"fan_modes": [...], "swing_modes": [...], "temperatures": [...]}` in
  Home Assistant's words, and the entity updates its `fan_modes`,
  `swing_modes` and temperature control from it when the mode changes. A
  mode with one temperature offers no temperature control. The gate compares
  `offers` with the wig mode by mode, refuses any difference, and refuses a
  lattice whose modes differ when `offers` is missing. Read it straight off
  the lattice:

  ```python
  def offers(self, hvac_mode):
      mode = HVAC_MODES.get(hvac_mode)
      cells = [c for c in self.lattice.cells if c.mode == mode]
      fans = [f for f in self.lattice.fan_modes if any(c.fan == f for c in cells)]
      swings = [s for s in self.lattice.swing_modes if any(c.swing == s for c in cells)]
      return {
          "fan_modes": [ha_fan_mode(f) for f in fans],
          "swing_modes": swings,
          "temperatures": sorted({c.temp for c in cells if c.temp is not None}),
      }
  ```
- **The entity's words are Home Assistant's; the lattice's stay verbatim.**
  `FAN_MODES`, `HVAC_MODES` and `SWING_MODES` map one onto the other, one to
  one, in the wig's order. Fan words have to be valid translation keys (no
  `+`), and each needs an English name in `translations/en.json`. Where core
  already has a word, use it: `medium_low` and `medium_high` are what
  `lg_infrared` uses.
- **Every send ends on HAIR's 50 ms terminator.** The gate checks every code
  converts to exactly `TerminatedCommand(ProntoCommand(code))`'s timings. Do
  not depend on upstream's `ProntoCommand`.
- **`lattice.py` and `command.py` import nothing from Home Assistant.**
  Anything the entity decides about which code to send belongs in them, not
  in `climate.py`.
- **A change sends the whole state.** Off sends the Off code. Changing fan,
  swing or temperature while off only records it, and the next Turn on sends
  it. The entity shows the cell that went out, not the request, and only
  after the send returned.
- **Restore from the entity's own stored data, never from state
  attributes.** Keep the assumed state in `extra_restore_state_data`, in
  Celsius and the entity's own words.

The gate runs the climate checks when it finds a `lattice.json` beside a
`lattice.py`, instead of the codebook ones.

### 4.4 Stamp the README

The generated README is where the trust chain becomes readable, and it is
the part most likely to be done carelessly. It must carry
([why](docs/background.md#the-readme)):

- What the device is, and the honest attribution. If the manufacturer was
  never established, say so: "Sold on Amazon as Sanmli TH-05 (ASIN
  B0DF7FPV55). Manufacturer per the Amazon listing: Sanmli. OEM not
  independently established."
- The HACS badge, using the
  `https://my.home-assistant.io/create-link/?redirect=hacs_repository` form,
  with the owner and repository filled in.
- **Tested or untested**, stated plainly, with the models it was confirmed
  against.
- The source wig, its content hash, **the Wig Shop commit it was read at**,
  and a link to it in the shop.
- Every fitter: handle, GitHub handle, date, how many rows they claimed, and
  the signing key fingerprint. Print handles as the fitter typed them. They
  are compared canonically and displayed verbatim, never rewritten.
- The independent-account count, as a number rather than a verdict.
- **Pooled row coverage**, beside the account count. "12 of 12 rows proven,
  by 1 account of 3" says something true that neither number says alone.
- **Frames per press, and where the number came from.** Say it is what the
  wig states, and say what to do if presses still get dropped.
- **The ditto count, if any row has one**, and that it is not adjustable.
- That the codebook was machine verified against HAIR's independent
  decoders, and in which directions.
- **What the live comb said**, with which HAIR, and on a lattice which field
  map read how many codes. `provenance_lines()` writes it.
- **How many codes the wig says were repaired, by tier**, when any were. Say
  it is the wig's own statement: repair records are signed by nothing.
- Installation, the entities it creates, and what to do when a code does not
  work.

House style from rule 6 applies. These are public files.

---

## 5. Verify

### 5.1 The full gate

```bash
.venv/bin/python verify/verify_wig.py --wig <wig> --integration <device>/<repo>
```

**Passes when** it exits 0. **Any mismatch fails the run.** Do not adjust
the gate to accommodate the generated code. Fix the generated code.

For a codebook integration it checks:

- **Forward, the encoder.** For every alias: `to_command()` produces raw
  timings, HAIR's decoder reads them, and the identity must equal the
  identity HAIR reads from the wig's own Pronto. Press state excluded on
  both sides.
- **Reverse, the decoder.** If the integration vendors an RX decoder, the
  wig's Pronto goes through *that* decoder and must produce the same
  identity again.
- **Coverage, both ways.** Every wig alias has exactly one codebook entry.
  Every codebook entry traces to exactly one wig alias.
- **Send count against the wig.** `DEFAULT_SEND_COUNT` in the generated
  `const.py`, read out of the file rather than imported, against the highest
  `send_count` the wig states. Below it is a refusal. Above it is allowed
  and noted.
- **Recipe conformance.** `WIG_RECIPE` against the wig, row by row, value by
  value. Mandatory the moment any row asks for a ditto or a bypass, optional
  while every row is plain
  ([why](docs/background.md#why-the-integration-has-to-reproduce-the-recipe)).

For a climate integration it checks that `lattice.json` is the wig's, that
`Resolver.resolve` agrees with HAIR's on every state, that `offers` matches
each mode, and that every code goes out as HAIR would send it (4.3).

### 5.2 The bench check

The gate proves the integration says what the wig says. It cannot prove Home
Assistant loads it. If the owner has a test Home Assistant with an emitter,
install the built integration there, add it, and confirm the entities appear
and a send goes out. **Never a production instance.** Whether a bench check
is needed before publishing is the owner's call; say plainly in your report
whether one was done.

---

## 6. Publish

**The owner decides, every time.** Before anything is pushed, all of these
hold:

- Stage 5 green.
- The input gate's fitting evidence real and recorded in the README.
- **The account count read, and the owner's ruling on it.** There is no
  threshold; publishing under the organization's name is a decision, and
  this is the moment it gets made.
- The shop clone refreshed (`./setup.sh`) and its commit stamped.
- Attribution done or honestly marked unknown.
- The owner has ruled on the repository name and the visibility.

Then, per chosen wig:

```bash
.venv/bin/python publish/publish_integration.py --wig <slug> --integration <path>
.venv/bin/python publish/publish_integration.py --wig <slug> --integration <path> --publish
```

**Without `--publish` it prints what it would create and touches nothing.**
Show the owner the dry run. With `--publish`, the script:

1. **Re-runs the gate itself**, full, against the tree as it stands.
   Anything short of a pass stops everything. It does not pass
   `--require-handles`; the account count reaches the owner as a number in
   the report.
2. Derives the repository name from the wig stem plus `-ir`, and the
   description and topics from the wig's `brand`, `model`, `kind` and
   `identifiers`.
3. **Refuses if the repository already exists.** Create only. Republishing
   is a different tool with different rules and it does not exist yet.
4. Creates it, sets description, topics and Issues, pushes a clean initial
   commit from a fresh `git init` rather than a subtree of this repository,
   then cuts the release.
5. **Stops for the owner between building and pushing**, which is what the
   dry run is for. They see what is about to be created.

After the push it is a normal repository with a normal pull request process,
and the factory does not reach back in.

**What the new repository must have**
([why](docs/background.md#repository-settings-that-do-not-live-in-a-file)):

- A name per 4.1, on `DAB-LABS`.
- **At least one repository topic.** Set topics that describe the device,
  from the wig's fields: brand, model, kind, protocol. Not `home-assistant`
  or `hacs-integration`; HACS strips both.
- **A repository description, and Issues enabled.**
- `hacs.json` with a `homeassistant` minimum matching the platform features
  used. Keep it to keys HACS's schema actually accepts; do not write
  `render_readme`.
- `custom_components/<domain>/brand/icon.png`.
- **A GitHub release at creation, `v0.1.0`, with generated notes**
  ([why](docs/background.md#why-the-release-matters-and-it-is-not-ceremony)).
- Shipped marked untested by others, carrying the fittings that came in with
  the wig.

**Credentials.** Use `gh` when it is present and authenticated. Fall back to
a token from the environment when it is not. Never read a credential from a
file in a repository, never echo one, and **never write anything about
credentials into public text**: not a path, not a scope list, not which
machine holds what.

**The credential may not be allowed to create repositories.** If the create
step is refused for permissions, stop and tell the owner. Do not look for
another credential. When the publish finishes, tell the owner, so that any
permission granted for it can be withdrawn.

The Wig Shop stays out of this. It is a separate repository with its own
validation, and the publish path does not write to it.

This is the one place you run the git and GitHub operations yourself
([why](docs/background.md#why-the-publish-path-is-automated)). Everything
else still gets handed over.

---

## 7. Maintain

### Updating a published integration

More claims, a successor wig, a moved send count or a stale stamp all go
through one command:

```bash
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path>
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path> --push
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path> --push --merge
```

Dry run, then a pull request, then a pull request that merges itself and
cuts the release. **`--merge` only when the owner has said so.** It waits
for the checks first and refuses to merge on a failure, or on not being able
to tell.

It never pushes to the default branch, never deletes a file (generated files
are overwritten; files that exist only in the published repository are left
alone and reported), and refuses to ship a change without a version bump
([why](docs/background.md#updates-are-automated-because-they-are-common)).

**A filename is not an identity.** A successor wig lands at the same path
with a new `wig_id` naming its ancestor in `supersedes`. Compare `wig_id`
and `supersedes` against what the published integration was built from;
never assume a filename means what it used to.

The `Built integrations` job in CI goes red when a built integration no
longer matches its wig, or its wig has left the shelf. This command is how
that red gets resolved.

### When it is proven

Independent fittings from distinct GitHub handles, on the shipped
integration, promote it from untested to tested. Update the README with the
models and handles.

A codec that has earned that is a candidate for upstream
`infrared-protocols`. **Read `reference/infrared-protocols/AI_POLICY.md`
before going anywhere near that** ([what it
says](docs/background.md#upstream-and-the-line-the-factory-does-not-cross)).
An agent never opens an upstream pull request, never drafts replies to
upstream maintainers, and never treats a green gate as readiness to
contribute. Raise it with the owner and stop there.

A shared codec package, `dab-labs-ir-codecs`, is decided for when the fleet
reaches roughly five integrations, and not built yet ([the
decision](docs/background.md#the-shared-codec-package-decided-but-not-yet-built)).

---

## Changing the factory itself

Everything above is about building an integration. This is about changing
`verify/`, `publish/` or the workflows.

### What CI tells you

Two workflows answer two different questions
([why](docs/background.md#ci-two-workflows-two-questions)).

**`ci.yml`: is the factory broken?** On every push, pull request and once a
week it runs ruff over `verify/` and `publish/`; the gate's own tests
(digest parity, gate behaviour, the climate checks) on Python 3.13 and 3.14;
and the full gate against every integration already built here, against its
wig in the shop. **Red always means work in this repository.**

**`shelf.yml`: what could the factory build?** Stage 2, weekly and on
demand. It never goes red because of a wig, only when it could not produce a
report at all.

**The HAIR pin.** `verify/HAIR_REF` names the HAIR release the gate judges
against, and it is the one place the pin lives. The weekly `ci.yml` run
judges against HAIR `main` instead, as a drift alarm: red on a Monday means
HAIR changed something the factory depends on. The pin has to be at least
0.14.2. **Bump it by hand in a pull request, one line, once CI is green
against the new release.**

### Before you commit

```bash
ruff check verify publish
.venv/bin/python verify/test_recipe.py --hair reference/HAIR
.venv/bin/python verify/test_gate.py --hair reference/HAIR
.venv/bin/python verify/test_climate.py --hair reference/HAIR
```

All green, on 3.13 and 3.14 if you touched anything that reads upstream
decoders.

### The row digest is contract

```
row_digest = sha256(normalized_pronto + "|d<ditto_count>" + "|b<0|1>")[:16]
```

`normalized_pronto` is HAIR's validator normalization then lowercased hex.
**The factory calls `wig_format.row_digest`; it never computes this
itself**, and `verify/test_recipe.py` fails if `verify_wig.py` ever imports
`hashlib`. Two things are deliberately OUT of the digest and must never be
added: the alias, and the send count
([why](docs/background.md#the-transmit-recipe-and-what-a-claim-actually-binds)).

The recipe lives on the signal:

| Field | Meaning | In the digest |
|---|---|---|
| `send_count` | send the whole blob again, after a pause | no |
| `ditto_count` | repeat frames the encoder appends inside one transmission | yes |
| `bypass_protocol` | skip the re-encode, put the raw blob on the air | yes |

If you touch the recipe reader or anything near the digest, re-run
`verify/test_recipe.py`. It pins the published digest layout against
hand-computed vectors, proves both exclusions by demonstration (a rename and
a send-count change must not move a digest, a ditto and a bypass must),
checks the reader's clamping, and fails on a local `hashlib` import.

### Reading a fitting

- **The discriminator is the shape, never the version stamp.** A fitting
  with `content_hash` is pre-claims; one with `wig_id` and `rows` is a
  claims bundle. Use `wig_format.is_legacy_fitting` and `is_claims_bundle`.
- **A pre-claims fitting counts toward nothing.** The gate names it and
  moves on.
- **Coverage and the account count are different numbers.** Coverage is rows
  proven, pooled. The count is distinct people who proved all of them. Print
  both.
