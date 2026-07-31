# WigFactory: the build workflow

You are a coding agent working in this repository. Your job is to turn one
**wig** into one installable Home Assistant integration.

Work through the steps in order. **Do not skip ahead.** Step 4 is a gate: if
it does not pass, you do not continue to step 5, and you do not publish
anything. That gate is the reason this repository exists.

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
   change from Timing objects to flat integers
   (home-assistant/core#172209). Generate against what is in `reference/`
   today, not against what you remember.
4. **Tests never need real hardware.** Everything is timings in and timings
   out. If a test wants a blaster, the test is wrong.
5. **Codecs are written from protocol specifications only.** No code
   derived from GPL or LGPL implementations: not IRremoteESP8266, not
   ESPHome's C++, not LIRC. Timing constants are protocol facts and are
   fine. Code structure is not. This keeps the eventual donation to
   `infrared-protocols` unencumbered, and it is not negotiable.
6. **Public text has a house style.** No em dashes anywhere. No AI tells:
   no rows of check marks, no emoji sprays, no "delve", no breathless
   summary paragraphs. Never name an AI vendor or assistant product in a
   README, a code comment, a commit message or an issue. Write like a
   person who built the thing.
7. **Never key identity on an entity_id.** `lg_infrared` shipped a config
   entry whose unique_id was derived from the infrared entity_id and had
   to walk it back with a migration. Learn it here for free.
8. **Ask before publishing.** Steps 1 through 6 are yours. Step 7 pushes
   to a public organization under the owner's name, and the owner rules on
   it.

---

## 1. Fetch the references

```bash
./setup.sh
```

This shallow clones into `reference/`:

| Path | What it is | Why you need it |
|---|---|---|
| `reference/HAIR` | The HAIR integration | Its decoders are the independent witness in step 4, and `wig_format.py` is the input parser |
| `reference/WigShop` | The Wig Shop | Where wigs come from. The factory reads the merged file everybody else sees, not somebody's local export |
| `reference/home-assistant-core` | Home Assistant core, `dev`, sparse | `homeassistant/components/lg_infrared` is the target output shape; `homeassistant/components/infrared` is the platform contract |
| `reference/infrared-protocols` | The upstream codec library | Tells you which protocols upstream can already encode and decode, and what a module that graduates upstream has to look like |
| `reference/integration_blueprint` | ludeeus's HACS scaffold | Repository level furniture: workflows, `hacs.json`, gitignore |

`setup.sh` also builds the verification environment: it finds the newest
Python 3.12 or later on the machine, creates `.venv`, and installs
`verify/requirements.txt`. **3.12 is a hard floor**, because HAIR's decoders
use PEP 695 type parameters and the gate imports them directly. If setup
reports no suitable interpreter, install one and run it again; it will not
guess and it will not silently skip the gate.

**There is a second floor, and it is softer.** Upstream `infrared-protocols`
8.2.1 requires Python 3.14 or newer, which is why Home Assistant runs 3.14.
Below that it cannot be installed, so a 3.12 or 3.13 environment runs the
gate on HAIR's own decoders alone: workable, and a smaller protocol set, with
no local polyfill for NEC, and none for GE air conditioners either: those
are the only two protocols in HAIR's registry with no local fallback, so
without upstream the registry drops them entirely and the gate refuses those
wigs as undecodable. NEC is the most common consumer protocol there is, so
this matters the moment a television wig arrives. `setup.sh` says which set
you have. The
requirement carries an environment marker so pip skips it cleanly rather
than failing, because a requirements file resolves as one transaction and an
unsatisfiable line otherwise takes `cryptography` down with it, leaving a
venv that cannot verify a single signature.

**`setup.sh` never runs itself.** There is no timer, no daemon and no
auto-update. You run it, it fetches and hard resets every clone to its
remote, and the clones then sit still until you run it again. That is
deliberate: a build has to be reproducible, and a reference that moved
underneath you halfway through is a build you cannot explain afterwards.

The practical rule is **run it at the start of a build**, and again before
any build whose output you intend to publish. A stale Wig Shop clone is
missing fittings that landed since, which does not make the build wrong,
only narrower than it needed to be.

---

## 2. Read the wig and run the input gate

The input is one `.wig.json` file. Name it either way:

```bash
# by shop slug, resolved from reference/WigShop and stamped with its commit
.venv/bin/python verify/verify_wig.py --wig sanmli-candles-th05 --gate-only

# or by path, for a wig that is not in the shop
.venv/bin/python verify/verify_wig.py --wig wigs/whatever.wig.json --gate-only
```

**Prefer the slug.** It reads the merged file every contributor sees, and it
records the shop commit, which is what makes the fitting evidence
reproducible later. Fittings accumulate over time, so "three distinct
accounts" is a claim about a moment; `WigShop@<sha>` is how somebody checks
that claim a year from now. A wig named by path carries no such record and
the gate will not invent one.

Run the gate before you look at anything else.

It enforces the hard requirements, and all of them are refusals, not
warnings:

1. **It parses** as `hair-wig/1` or `hair-wig/2` through HAIR's own
   `wig_format.parse_wig`. Not a lookalike parser you wrote. The same code
   the user's install runs on import.
2. **It carries at least one complete fitting.** Complete means `confirmed`
   covers every fitting row and `failed` is empty. A wig with no fitting is
   a spreadsheet, and this factory does not take spreadsheets.
3. **Every fitting's `content_hash` matches** the wig's recomputed
   canonical hash. A stale hash means the codes moved after somebody proved
   them, and the proof no longer covers what is in the file.
4. **Signatures verify** where a fitting carries `key` and `sig`. A fitting
   that claims a signature and fails it is a hard stop. An unsigned fitting
   passes with a note.
5. **Every signal decodes, and to one protocol family.** Mixed protocol
   wigs are out of scope: one wig, one codec. A signal that will not decode
   at all is out of scope too, because there is nothing to generate from
   raw replay.

It also **counts distinct contributors**, and this is not the same as
counting handles. The `github` field is free text somebody typed, so one
account arrives as `dab`, `@dab`, `DAB` and `github.com/dab`. The gate
compares a canonical form, counts only fittings that actually name a GitHub
account, and says out loud when two fittings collapse to one person. A
display handle names nobody a reviewer can check, so it never counts toward
the bar.

The standing promotion bar is **three complete fittings from three distinct
GitHub accounts**. The gate reports the count on every run and enforces it
only when you pass `--require-handles 3`.

**Exemptions are written down or they do not exist.** Not passing the flag
is how a bar quietly stops being a bar, so a waiver lives in
`EXEMPTIONS.md` and the gate reads it:

```bash
.venv/bin/python verify/verify_wig.py --wig <slug> --integration <path> \
  --require-handles 3 --exemption EXEMPTIONS.md
```

With an entry matching the wig, the handle failure becomes a loud note that
quotes the reason back into the build output, so the published artifact's
log says out loud that it published under a waiver and why. With no matching
entry it still refuses. Each entry names the wig, the bar waived, the
reason, who ruled it, the date, and the condition that retires it. One wig's
waiver never covers another.

### Matrix wigs

A `hair-wig/2` wig carries a climate block instead of, or as well as, a list
of signals: a lattice of cells, one per complete device state. There is no
codebook to build a second implementation of, so the checks are about the
lattice contradicting itself, and on real files they find plenty.

- **Completeness.** Home Assistant offers the user every combination of the
  modes, fan modes and swing modes the integration advertises. A hole is not
  a missing table row, it is a control that silently does nothing.
- **Collapsed rows are a feature, not a fault.** A row where every
  temperature sends one code means the device ignores temperature there.
  Daikin does it in 19 rows of 40. The integration must not offer a
  temperature control in those combinations.
- **Partial collapse is a defect.** If a row varies with temperature at most
  settings and then two adjacent values collide, one of them transmits the
  wrong state. On real files it is always a neighbour: 18 carrying 19's
  frame.
- **Frame shape.** Every cell of one device sends the same protocol, so every
  cell should have the same frames of the same lengths. A short frame is a
  truncated capture and refuses. A stray burst after the last frame is
  capture noise and only notes.
- **Celsius is asserted, not assumed.** The format carries a `unit`, and a
  Fahrenheit lattice read as Celsius is a silent thirty degree error.

Fittings on a matrix wig attest the **dimension checklist**, a deterministic
12 to 20 row walk, not the whole lattice. That is HAIR's definition and the
gate reads it from HAIR rather than reimplementing it. Nobody fits 960 cells.

To see how a device packs its state, run the microscope:

```bash
.venv/bin/python verify/derive_fields.py --wig <wig>
```

It lines up every cell, finds the bit positions that move, groups them into
runs and says which dimension each run tracks. On Gree that is 15 moving bits
out of 66; on Panasonic, 18 out of 216. It is not a check and it never
refuses. The judgement is still yours: deciding a four bit run really is
temperature, recognising a checksum, choosing what the entity exposes. The
tool exists so you apply that judgement to a field map rather than to 63KB
of hex.

It also reads **send times** off the fittings. A fitting made on HAIR 0.9.0 or
later carries `send_times_used`: how many times each signal had to be
transmitted per press before the device answered, during the session that
proved it. Read the number the gate prints, because step 5 has to ship it.

Three rules about that field, and they are all easy to get wrong:

- **Absent is not 1.** A fitting without it predates the field and claims
  nothing. An explicit `1` is a real measurement: the fitter had the control
  and one send was enough. Never treat the first as the second.
- **Aggregate by maximum, never mean.** Send times is a threshold, not a
  tendency. A fitter reporting 3 is saying fewer than three was unreliable
  where they stood, so averaging `[1, 3, 3]` to 2 produces a number that
  satisfies nobody who measured.
- **Read the spread, not just the max.** The gate prints both. Three fittings
  saying 1 and one saying 8 is not a device that needs eight frames, it is one
  room with a weak blaster or a bad angle. That is a judgement call, so make
  it deliberately rather than letting the max make it for you.

Record what the gate printed. The content hash, the shop commit, the fitting
handles and dates, the HAIR version and the send times go into the generated
README in step 6, and you cannot reconstruct them later.

**If a wig fails this gate, stop and report why.** Do not repair the wig.
Corrections are the fitter's job, in HAIR, with a fresh fitting. In
particular, never edit a `github` value to make a count come out better: the
signature covers it, and rewriting it forges somebody's attestation.

Then copy the wig into `wigs/` per ground rule 1 and work from that copy.

---

## 3. Establish the device and derive the codebook

**Protocol.** The gate already told you. Check `reference/infrared-protocols`
for the matching command class and note precisely what it can do. As of this
writing `RC5Command` can encode and cannot decode, which matters in step 5.

**Kind.** Read the wig's `kind` field. It decides which device class wrapper
you generate alongside the buttons:

| kind | wrapper platform |
|---|---|
| `tv`, `settopbox`, `projector`, `soundbar`, `receiver` | `media_player` |
| `light`, `candles` | `light` |
| `fan` | `fan` |
| `ac`, `heater` | `climate` |
| `blinds`, `screen` | `cover` |
| anything else, or absent | buttons only, and say so in the README |

Buttons are always generated, one per signal. The wrapper is additional.

**Naming.** Ruled and not open for redesign:

- Repository: `<brand>-<kind>-<model>-ir`, lowercase kebab, `kind` squashed
  to one word with no inner dashes.
- Domain: `<brand>_<model>_ir`, lowercase snake. Per device, not per brand:
  `<brand>_ir` collides the day that brand sells a second product.
- Pieces drop out when genuinely absent. Fall back to the wig's name slug
  when almost nothing is known.

The wig file in the Wig Shop is `<brand>-<kind>-<model>.wig.json`, so the
repository name is the wig's stem plus `-ir`. That is deliberate. A wig
carries its own future name from the day it lands.

**The `-ir` suffix names the medium, and it goes in the domain too.** Radio
frequency is the obvious second medium, and `-rf` is the obvious second
suffix. A repository suffix alone would not be enough: two repositories can
have different names and still ship components with the same domain, and
Home Assistant cannot load two integrations that share one. So an IR and an
RF version of one device need `sanmli_th05_ir` and `sanmli_th05_rf`, not one
`sanmli_th05` fought over.

The domain is close to invisible to users. It is the folder under
`custom_components/`, the string in `manifest.json`, `DOMAIN` in `const.py`,
and the prefix on log lines. It does not reach entity IDs, because entities
are named from the device. But it is baked into the config entry and the
device registry the moment somebody installs, so changing it later is not a
rename: their integration goes unavailable, they re-add it, and they lose
their entity IDs and history. Get it right before the first publish, because
after that it is permanent.

**Casing, ruled and not open.** The slug and the domain are lowercase.
Home Assistant requires it of the domain and enforces it in hassfest, the
Wig Shop enforces it on the wig filename with a regex, and GitHub lowercases
repository topics itself. Casing is not a discoverability lever either:
GitHub search is case insensitive, so what surfaces a repository is the
description, the topics and the README body, not the shape of the slug.

**Identity fields feed labels, never identifiers.** The wig carries
`brand`, `model`, `kind` and `name` with real human casing, and those are
the right source for every human-facing string: the `name` in
`manifest.json` and `hacs.json`, the README heading, the repository
description, the topics. They are the wrong source for the slug, the domain
or the folder, for three reasons.

- They are mutable. The canonical hash covers only `alias`, `pronto` and
  `send_count`, so brand and model can be corrected without invalidating a
  single fitting. The filename cannot drift, because under the shop's
  immutability rule a rename is a new file.
- They are free text. `name` on the candle wig is `Candles (Tea Light)`,
  and parentheses are not legal in a repository name. Deriving identifiers
  from them means a sanitizer, which is a hand-applied casing spec hiding
  in code.
- `model` is `TH-05`. Field-derived naming reintroduces the inner dash that
  the squashing rule exists to remove, and then nothing can tell a segment
  separator from part of a model number.

**The codebook table.** Derive it mechanically from the decoded identities,
never by hand and never by pattern matching on aliases:

- One entry per signal, keyed on the wig's alias verbatim.
- The value is the decoded command. The decoded address is one module level
  constant, and every signal must share it. If they do not, the wig is two
  devices and step 2 should have caught it.
- **Press state is excluded.** The RC-5 toggle bit is frozen at capture
  time and means nothing about which button was pressed. It never enters
  the codebook. The integration flips it per press instead, exactly as
  HAIR does.

---

## 4. Build the verification gate and run it

**Build this before you build the integration.** It is the gate, and a gate
you write after the thing it guards is a gate you wrote to pass.

`verify/verify_wig.py` already implements it. Your job is to satisfy its
contract, which is what makes the generated `codes.py` machine checkable:

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

Then run the full gate:

```bash
.venv/bin/python verify/verify_wig.py \
  --wig <wig> --integration <device>/<repo>
```

What it checks:

**Forward, the encoder.** For every alias: `to_command()` produces raw
timings, HAIR's decoder reads them, and the identity must equal the identity
HAIR reads from the wig's own Pronto. Press state excluded on both sides.

**Reverse, the decoder.** If the integration vendors an RX decoder, the
wig's Pronto goes through *that* decoder and must produce the same identity
again. This is the direction that proves the integration can hear the
physical remote correctly, and it is only possible because the decoder is a
separate implementation from the encoder.

**Coverage, both ways.** Every wig alias has exactly one codebook entry.
Every codebook entry traces to exactly one wig alias. A generated integration
that quietly dropped three buttons passes every other check.

**Send count against the evidence.** `DEFAULT_SEND_COUNT` in the generated
`const.py`, read out of the file rather than imported, against the maximum
`send_times_used` across the complete fittings. Below the proven threshold is a
refusal. Above it is allowed and noted, since more frames cost airtime and not
correctness. This one check is not about the codec at all: a codec can be
perfectly right and the integration still look broken, because the frames never
arrived.

Where the HAIR checkout is 0.9.0 or newer the gate calls HAIR's own
`fitting_send_times_max` rather than aggregating itself. HAIR's docstring calls
that function the single aggregation point for send times, shared with ADOPT
DEVICE and the shop index, and two implementations of one rule is how the rule
drifts. The factory keeps a fallback reader for older checkouts, kept in step
with HAIR's the same way `github_key` is kept in step with the shop's. If you
touch either reader, re-run the vectors:

```bash
.venv/bin/python verify/test_send_times.py
```

It compares the factory's reader against HAIR's on every shape the field has
been seen to carry, and refuses if the two disagree by so much as one value. A
fallback that drifts from the thing it falls back to is worse than no fallback,
because it fails quietly and in the direction nobody checks.

**Any mismatch fails the run.** Do not adjust the gate to accommodate the
generated code. Fix the generated code.

---

## 5. Generate the integration

Mirror `reference/home-assistant-core/homeassistant/components/lg_infrared`
for the integration, and `reference/integration_blueprint` for the
repository furniture around it.

```
<device>/
  <brand>-<kind>-<model>-ir/
    custom_components/<domain>/
      __init__.py          forward the platforms, set up and unload the entry
      codes.py             the codebook from step 3, plus WIG_ALIASES
      const.py             DOMAIN and configuration keys
      config_flow.py       emitter EntitySelector, optional receiver EntitySelector
      entity.py            base entity setting DeviceInfo, plus the platform mixins
      button.py            one button per code
      <wrapper>.py         the device class wrapper chosen in step 3
      event.py             receiver side, when a decoder is vendored
      decoder.py           the vendored RX decoder, when upstream cannot decode
      manifest.json
      translations/en.json
    hacs.json
    README.md
    LICENSE
    .github/workflows/lint.yml
    .github/workflows/validate.yml
    .gitignore
```

The details that are not obvious:

**`manifest.json`** carries `"dependencies": ["infrared"]`,
`"iot_class": "assumed_state"`, `"integration_type": "device"`,
`"config_flow": true`, `"version"`, and `"codeowners"`. IR is fire and
forget, so assumed state is not a shortcut, it is the truth.

**Entities do the IR work through the platform's mixins.**
`InfraredEmitterConsumerEntity` provides `_send_command`.
`InfraredReceiverConsumerEntity` provides the `_handle_signal`
subscription. Read them in `reference/home-assistant-core` rather than
reimplementing them.

**The config flow** uses an EntitySelector for the emitter and an
**optional** EntitySelector for the receiver. Receivers are optional
everywhere in this ecosystem and this is not the place to change that.

**`event.py`** decodes an incoming signal, matches it against the codebook,
and fires an HA event. It must carry an `unknown` fallback so that a code
outside the enum never raises, and it must tolerate both timing shapes
(Timing objects with `.high_us` and `.low_us`, and flat integers). That
dual shape tolerance is what let HAIR skate through the migration that broke
`lg_infrared`. Copy the posture from HAIR's `event_parser.py`.

**`decoder.py`** exists only when upstream cannot decode the protocol.
Adapt it from HAIR's `custom_components/hair/decoders/`, which is written
from specifications and licensed cleanly for exactly this. Keep the upstream
shape: a classmethod `from_raw_timings(timings: list[int]) -> Self | None`,
signed microseconds with positive marks and negative spaces, bounds checked
indexing so it never raises on malformed input.

**RC-5 press state on transmit.** One toggle value per config entry, mod 2,
flipped after each send in which at least one emitter accepted the command.
Not per entity, not per button.

**Frames per press comes from the fittings, not from you.** Real remotes do
not send one frame. RC-5 re-sends the same code every 114ms for as long as the
key is held, so a physical press is three or four frames, and a battery
powered device that duty cycles its receiver can sleep straight through a
single frame. The symptom is a button that works on the first press sometimes
and needs three other times, with no pattern, on a codebook that is completely
correct. The gate cannot see it, because encoding and decoding are both fine.
So:

- `const.py` carries `DEFAULT_SEND_COUNT`, `MIN_SEND_COUNT = 1`,
  `MAX_SEND_COUNT = 10` and a gap between frames of about 100ms.
- `DEFAULT_SEND_COUNT` is the **maximum `send_times_used` across the complete
  fittings**, which is the number the gate prints. Not a number you chose. The
  gate refuses a default below the proven threshold, because shipping under it
  reproduces a fault somebody already found and wrote down.
- All the frames in one press share one RC-5 toggle value, and the toggle
  advances once, after the last of them. A press is one press. Advancing per
  frame tells the device it was pressed three times, which is exactly what
  toggle exists to distinguish.
- Expose it in the options flow. Send times measures a room, and the next
  person's room is not this one.
- **When no fitting carries the field**, the gate says so and stops short of
  guessing. Ask the fitter how many sends the device actually needed, use that,
  and say in the README that the number came from the fitter rather than from a
  fitting. Do not silently ship 1: absent is not a measurement of 1, and a
  default nobody measured is the kind of thing that reads as a broken
  integration.
- A wig signal carrying its own `send_count` above 1 is a **different claim**.
  That is a property of the code, where send times is a property of the room. A
  single setting cannot express a per code repeat; generate one for that code
  or say plainly in the README that it is sent once.

**Requirements are PyPI specifiers only.** Never a VCS URL: hassfest and
HACS both pass it and the config flow then fails with a 500 at runtime, which
is a miserable afternoon. Never a space around the `@` in a requirement
string either.

Write tests alongside. Round trip every codebook entry through encode and
decode, assert the vendored decoder agrees with HAIR on every wig signal, and
mock every connection.

---

## 6. Stamp the README

The generated README is where the trust chain becomes readable, and it is
the part most likely to be done carelessly. It must carry:

- What the device is, and the honest attribution. If the manufacturer was
  never established, say so: "Sold on Amazon as Sanmli TH-05 (ASIN
  B0DF7FPV55). Manufacturer per the Amazon listing: Sanmli. OEM not
  independently established." A confidently wrong manufacturer is worse
  than an honest unknown, and much worse if the codec ever goes upstream
  carrying it.
- The HACS badge, using the
  `https://my.home-assistant.io/create-link/?redirect=hacs_repository`
  form, with the owner and repository filled in.
- **Tested or untested**, stated plainly, with the models it was confirmed
  against.
- The source wig, its content hash, **the Wig Shop commit it was read at**,
  and a link to it in the shop. The commit is what lets a reader reproduce
  the fitting evidence exactly as the factory saw it, rather than having to
  trust that the count was right on the day.
- Every fitting: handle, GitHub handle, date, HAIR version, the signing key
  fingerprint, and the send times it recorded. Print handles as the fitter
  typed them. They are compared canonically and displayed verbatim, never
  rewritten.
- The distinct-account count against the promotion bar, and the exemption if
  one applies.
- **Frames per press, and where the number came from.** Say the aggregate and
  the basis: "3, the maximum across 1 reporting fitting" or "3, from the
  fitter, no fitting records it". Then say what to do if presses still get
  dropped, because that is the single most likely thing to need adjusting on
  hardware other than the bench set. A reader who knows the number is evidence
  from somebody's room will reach for the setting instead of filing a bug.
- That the codebook was machine verified against HAIR's independent
  decoders, and in which directions.
- Installation, the entities it creates, and what to do when a code does
  not work.

House style from rule 6 applies. These are public files.

---

## 7. Publish, and only when the owner says so

Gates, all of them, before anything is pushed:

- Step 4 green in both directions.
- The input gate's fitting evidence real and recorded in the README.
- **`--require-handles 3` green, or a written exemption naming this build.**
  The POC has one. Nothing else does by default.
- The shop clone refreshed (`./setup.sh`) and its commit stamped.
- Attribution done or honestly marked unknown.
- The owner has ruled on the repository name and the visibility.

Then:

- New repository on `DAB-LABS`, named per step 3.
- **At least one repository topic.** The HACS action checks that the topic
  list is not empty and nothing more. It does not require any particular
  topic, and the widely repeated claim that `home-assistant` and
  `hacs-integration` are mandatory is false: both sit on HACS's own
  `TOPIC_FILTER` denylist, which strips them because every HACS repository
  carries them and they are worthless for search. Set topics that describe
  the device instead, from the wig's fields: brand, model, kind, protocol.
- **A repository description, and Issues enabled.** Both are checked by the
  action, neither lives in a file, and both are easy to forget because they
  are set on the repository rather than committed to it.
- `hacs.json` with a `homeassistant` minimum matching the platform features
  used. Keep it to keys HACS's schema actually accepts; it uses
  `PREVENT_EXTRA`, so an unknown key is a hard validation failure rather
  than something ignored. `render_readme` is accepted but vestigial, with no
  consumers in current HACS, so do not write it.
- `custom_components/<domain>/brand/icon.png`. The action's brand check
  wants it, and since Home Assistant 2026.3 an integration can ship its own
  brand images rather than registering in `home-assistant/brands`. Note the
  gap: HACS's own panel still reads `brands.home-assistant.io` for update
  entity icons, so a locally shipped icon renders everywhere in Home
  Assistant except inside HACS itself. Living with a placeholder there is
  fine; the brands repository submission is optional and separate.
- **A GitHub release at creation, `v0.1.0`, with generated notes.**
- Ship marked untested by others, carrying the fittings that came in with
  the wig.

**Why the release matters, and it is not ceremony.** With no releases at
all, HACS installs from the default branch and treats the branch HEAD as the
version, showing users a seven character commit SHA. Every commit that lands
then reads as an available update, including a README typo and every merged
pull request, and there are no release notes to explain any of it. That is
how people learn to ignore your updates.

The moment one release exists, HACS stops looking at the branch entirely:
its version selection checks for a release first and only falls through to
the branch when there is none. So cutting `v0.1.0` at creation is what makes
main safe to commit to. It also keeps the door open to the HACS default
store later, which hard-requires a published release and does not accept a
bare tag.

The Wig Shop stays out of this. It is a separate repository with its own
validation, and the publish path does not write to it.

---

### 7.1 The publish path is automated, and that is a scoped exception

Ground rule 8 and the owner's standing instruction are that you hand over
git commands rather than running them. **The publish path is the exception,
and only the publish path.** Everything else still gets handed over.

The reason is volume: this is meant to run over many wigs, and a human
pasting repository creation commands per device is the bottleneck the
factory exists to remove.

The shape:

**Survey first.**

```bash
.venv/bin/python verify/survey_shop.py
```

It runs the input gate over every wig in the shop clone and sorts the results
into READY, FITTINGS, DEFECTS, UNUSABLE and BUILT. Every criterion is
something the gate already computes, so nothing here is judgement. That
listing is the proposal the owner picks from. **Do not build anything before
they have picked.**

DEFECTS is the bucket worth reading. A wig lands there when the gate found
something wrong with the codes rather than with the paperwork: a lattice
hole, a truncated frame, two temperatures sharing one payload. Those are
fixed at the source and never here.

**Then publish, per chosen wig.**

```bash
.venv/bin/python publish/publish_integration.py --wig <slug> --integration <path>
.venv/bin/python publish/publish_integration.py --wig <slug> --integration <path> --publish
```

Without `--publish` it prints what it would create and touches nothing. The
script does all of it:

1. **Re-runs the gate itself**, with `--require-handles 3` or a matching
   `--exemption`. Non-zero exit stops everything. This is load bearing: a
   green run from earlier proves nothing about the tree now, so publication
   is gated by construction rather than by whoever remembered.
2. Derives the repository name from the wig stem plus `-ir`, and the
   description and topics from the wig's `brand`, `model`, `kind` and
   `identifiers`.
3. **Refuses if the repository already exists.** Create only. Once
   published, an integration has its own life: somebody opens a pull
   request, it gets merged, and the repository now holds commits the factory
   has never seen. A publisher that re-pushed would destroy them silently.
   Republishing is a different tool with different rules and it does not
   exist yet.
4. Creates it, sets description, topics and Issues, pushes a clean initial
   commit from a fresh `git init` rather than a subtree of this repository,
   then cuts the release.
5. **Dry run unless `--publish` is passed.** A bad run leaves a public
   repository carrying the organization's name, and unlike a bad commit you
   cannot quietly amend it away.
6. **Stops for the owner between building and pushing.** They see what is
   about to be created. After the push it is a normal repository with a
   normal pull request process, and the factory does not reach back in.

**Updating a published integration is a different command.** A wig gets
refitted, combed or repaired; the send count moves; the stamp goes stale. That
happens far more often than a first publish, so it is automated too:

```bash
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path>
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path> --push
.venv/bin/python publish/update_integration.py --wig <slug> --integration <path> --push --merge
```

Dry run, then a pull request, then a pull request that merges itself and cuts
the release.

`--merge` **waits for the checks first** and refuses to merge on a failure, or
on not being able to tell. That is not politeness. The first automated update
merged its own pull request about twenty seconds into a forty-nine second
validation run, and deleting the branch mid-run made the HACS action's lookup
of the head ref return Not Found. The visible symptom was a red cross on a run
that no longer mattered; the real problem was that the merge had not waited for
anything and would have gone through had the run been genuinely failing.

Three rules make the last of those safe to run without watching:

- **It never pushes to the default branch.** Every change arrives as a pull
  request, because a published integration accrues commits the factory never
  saw and that is where the collision becomes visible.
- **It never deletes.** Files the factory generates are overwritten; files
  that exist only in the published repository are left alone and reported.
  Somebody adding a CONTRIBUTING should not lose it to a stamp refresh.

It also refuses to ship a change without a version bump. Home Assistant shows
the manifest version to users and HACS tracks the release tag, so a change
that moves neither means somebody's install quietly stops matching what it
says it is.

**Always invoke through `.venv/bin/python`.** These scripts run the gate in
process, and the gate needs what `verify/requirements.txt` installs. They are
not marked executable on purpose: a shebang cannot portably point at a
relative virtual environment, so a directly executed script would find the
system interpreter and fail somewhere less obvious than the first line.

**Credentials.** Use `gh` when it is present and authenticated, so the
credential stays in the OS keychain and nothing here ever handles a secret.
Fall back to a token from the environment when it is not. Never read a
credential from a file in a repository, never echo one, and **never write
anything about credentials into public text**: not a path, not a scope list,
not which machine holds what. Naming where a secret lives is a leak even
when the secret is not in the file.

---

## 8. When it is proven

Three complete fittings from three distinct GitHub handles, on the shipped
integration, promotes it from untested to tested. Update the README with the
models and handles.

A codec that has earned that is a candidate for upstream
`infrared-protocols`. Upstream asks that a library contribution links a core
pull request, even a draft, so the library stays tied to real usage.

**Read `reference/infrared-protocols/AI_POLICY.md` before going anywhere near
that, because it constrains this project specifically.** The Open Home
Foundation policy says, in its own words:

- "We do not allow autonomous agents to be used for contributing to our
  projects." Pull requests believed to be created autonomously get closed.
- "All contributions must be reviewed and understood by the contributor
  before submission. You should be able to explain every change in a pull
  request you submit."
- "Do not use AI to generate answers to questions from maintainers."

None of that blocks the factory. It does draw a hard line across it. **This
repository's output is publishable under DAB-LABS as generated code that has
passed the gate. It is not submittable upstream in that state.** Upstreaming
is a separate act by a human who has read the codec line by line,
understands why every timing constant is what it is, and can defend it in a
review thread in their own words.

So: an agent never opens an upstream pull request, never drafts replies to
upstream maintainers, and never treats a green gate as readiness to
contribute. The gate proves the codec matches the captured signals. It does
not transfer anybody's understanding, and understanding is what upstream is
asking for.

Raise it with the owner and stop there.

---

### 8.1 The shared codec package, decided but not yet built

Every generated integration vendors its own `decoder.py`. At one integration
that is correct. At a fleet it means one bug lives in N copies, and the gate
cannot pre-empt the bug that matters: it proves a codec against the signals
in the wigs it was run with, and says nothing about malformed input, a new
timing shape, or a protocol edge no wig has exercised. Home Assistant has
already changed the timing shape handed to receivers once, which is what
broke `lg_infrared`.

**Decision: a shared package, `dab-labs-ir-codecs` on PyPI, when the fleet
reaches roughly five integrations.** Not before. Generated integrations then
declare it in `requirements`, which is a PyPI specifier and so already legal
under the no-VCS-URLs rule.

What it buys: one place to author the fix, one test suite exercising the
edges no wig covers, N one-line pull requests to ship rather than N code
reviews, and a staging ground where codecs mature under this project's own
governance before a human ports one upstream. That last part matters
because, per the policy above, upstreaming is a human act on a human's
schedule, so codecs need somewhere to live and be exercised in the meantime.

Two things to get right when it happens:

**Pin with `~=`, not `==`.** Home Assistant installs integration
requirements into one shared environment. A user with three of these
integrations pinned to three exact versions creates a conflict, because only
one version can be present. Compatible-release specifiers let them coexist.

**Two edits ship a codec fix, and only one of them does the work.** The
requirement specifier is what pulls the new package; `manifest.json`'s
`version` is a label Home Assistant displays. Bump the version and forget
the specifier and everything still looks right: HACS offers an update, the
user takes it, and they run new integration files against the old package.
Silent, and successful from every visible angle. Whatever automates the
fleet bump treats the specifier as load bearing.

Note also that nothing propagates on its own. Home Assistant installs a
requirement only when it is not already satisfied
(`homeassistant/requirements.py`), so a PyPI release alone never reaches an
existing install. It always travels through a manifest edit, a HACS update
the user chooses, and a restart. That is a safety property, not a
limitation: a package release that changed behaviour inside installs which
saw no update would be an incident with nothing to roll back to.
