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
only when you pass `--require-handles 3`. That is on purpose: the candle POC
carries a written exemption, and an exemption applied silently is not an
exemption.

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

- Repository: `<brand>-<kind>-<model>-infrared`, lowercase kebab, `kind`
  squashed to one word with no inner dashes.
- Domain: `<brand>_<model>`, lowercase snake. Per device, not per brand:
  `<brand>_infrared` collides the day that brand sells a second product.
- Pieces drop out when genuinely absent. Fall back to the wig's name slug
  when almost nothing is known.

The wig file in the Wig Shop is `<brand>-<kind>-<model>.wig.json`, so the
repository name is the wig's stem plus `-infrared`. That is deliberate. A
wig carries its own future name from the day it lands.

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
  <brand>-<kind>-<model>-infrared/
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
- **Repository topics `home-assistant` and `hacs-integration`.** HACS
  validation fails without both, and the failure message does not tell you
  that.
- `hacs.json` with a `homeassistant` minimum matching the platform features
  used.
- Ship marked untested by others, carrying the fittings that came in with
  the wig.
- Add the graduation pointer to the wig's entry in the Wig Shop index.

Give the owner the git commands. Do not run pushes yourself.

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
