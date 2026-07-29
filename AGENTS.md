# WigFactory: the build workflow

You are a coding agent working in this repository. Your job is to turn one
**wig** into one installable Home Assistant integration.

Work through the steps in order. **Do not skip ahead.** Step 4 is a gate: if
it does not pass, you do not continue to step 5, and you do not publish
anything. That gate is the reason this repository exists.

---

## 0. Ground rules

These apply to everything you write here.

1. **`reference/` is read only.** It holds shallow clones of other people's
   repositories. Read them, mirror their structure, never edit them, never
   commit them. `setup.sh` refreshes them; that is the only thing that
   writes there.
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
| `reference/home-assistant-core` | Home Assistant core, `dev`, sparse | `homeassistant/components/lg_infrared` is the target output shape; `homeassistant/components/infrared` is the platform contract |
| `reference/infrared-protocols` | The upstream codec library | Tells you which protocols upstream can already encode and decode, and what a module that graduates upstream has to look like |
| `reference/integration_blueprint` | ludeeus's HACS scaffold | Repository level furniture: workflows, `hacs.json`, gitignore |

Then set up the verification environment once:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r verify/requirements.txt
```

Python 3.13 specifically. HAIR's decoders use 3.12+ syntax and are tested
on 3.13.

---

## 2. Read the wig and run the input gate

The input is one `.wig.json` file. Run the gate before you look at anything
else:

```bash
.venv/bin/python verify/verify_wig.py --wig <path-to-wig> --gate-only
```

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

Record what the gate printed. The content hash, the fitting handles and
dates, and the HAIR version go into the generated README in step 6, and you
cannot reconstruct them later.

**If a wig fails this gate, stop and report why.** Do not repair the wig.
Corrections are the fitter's job, in HAIR, with a fresh fitting.

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
- The source wig, its content hash, and a link to it in the Wig Shop.
- Every fitting: handle, GitHub handle, date, HAIR version, and the signing
  key fingerprint.
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
pull request, even a draft, so the library stays tied to real usage. That is
a separate conversation and a separate piece of work, and it starts with
asking rather than opening a pull request.
