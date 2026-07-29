# WigFactory

Turns a proven wig into an installable Home Assistant integration.

A **wig** is one JSON file holding one remote's codes, captured with [HAIR](https://github.com/DAB-LABS/HAIR). This repo is the workshop where a wig becomes a real integration: a codebook, entities, a config flow, and a repository of its own with a HACS badge.

**This is not a program.** It is a workflow that an AI coding agent follows. The factory is [`AGENTS.md`](AGENTS.md). You clone this repo, open a coding agent in the folder, hand it a wig, and it builds.

---

## Why a wig and not a code database

Anyone can generate an integration from a table of IR codes. The interesting question is whether the result actually drives the hardware, and a table cannot answer that.

A wig can. Every wig that enters this factory carries a **fitting**: a per signal record that a named person pointed a blaster at the real device, pressed every button, and confirmed each one worked. The fitting is bound to a hash of the exact codes it tested and signed by the install that recorded it. Change a code afterward and the fitting stops matching.

So the factory starts from evidence rather than from a spreadsheet. That is the whole premise.

---

## Using it

You need Python 3.13, git, and a coding agent you can run in a folder.

```bash
git clone https://github.com/DAB-LABS/WigFactory.git
cd WigFactory
./setup.sh
```

`setup.sh` shallow clones the reference repositories into `reference/`, which is gitignored. They are read only. Nothing in the build ever edits them.

That includes the [Wig Shop](https://github.com/DAB-LABS/WigShop), so the wigs are already there when setup finishes. **Nothing updates itself.** There is no timer and no daemon: you run `setup.sh`, every clone is fetched and reset to its remote, and then it all sits still until you run it again. Builds have to be reproducible, and a reference that moved halfway through is a build you cannot explain afterwards. Run it when you start, and again before any build you intend to publish.

Then open your coding agent in the repo root and hand it a wig by name:

> Build an integration from `sanmli-candles-th05`.

The agent reads `AGENTS.md` and works through it in order. Output lands in a folder named for the device.

---

## The gate

The load bearing idea in this repo is that **an LLM writing an IR codec will be wrong some of the time.** That is not a reason to avoid the approach. It is a reason to check the work by machine before anybody installs it.

HAIR owns its own protocol decoders, and those decoders never see the generated code. That makes them an independent witness, and the factory uses them in both directions:

**Forward.** The generated codebook encodes a command. HAIR decodes the result. The identity it reads back must equal the identity HAIR reads from the wig's captured signal.

**Reverse.** The wig's captured Pronto goes through the decoder vendored into the generated integration. It must produce that same identity.

Both directions green means the encoder and the decoder in the generated integration agree with an implementation neither of them was derived from. Press state, like the RC-5 toggle bit, is excluded on both sides, because a toggle is which press it was and not which button.

Coverage is checked as a bijection: every signal in the wig has exactly one codebook entry, and every codebook entry traces back to exactly one signal. No silent drops, no invented codes.

Any mismatch fails the run before anything is published.

It also counts contributors rather than strings. The GitHub handle on a fitting is free text somebody typed, so one account shows up as `dab`, `@dab`, `DAB` and `github.com/dab`. Compared raw, one person on two installs supplies two of the three fittings that promotion requires without meaning to deceive anyone. The gate compares a canonical form, counts only fittings that name a checkable account, and says plainly when two fittings collapse to one person.

```bash
python3 verify/verify_wig.py \
  --wig sanmli-candles-th05 \
  --integration sanmli-candles-th05/sanmli-candles-th05-infrared
```

---

## What comes out

```
sanmli-candles-th05/
  sanmli-candles-th05-infrared/     ready to push to its own repository
    custom_components/sanmli_th05/
      codes.py                      the codebook, generated from the wig
      button.py  light.py  event.py
      config_flow.py  entity.py  const.py  __init__.py
      manifest.json  translations/en.json
    hacs.json  README.md  LICENSE
    .github/workflows/
```

One integration per device. The codebook is vendored inside it rather than published as a separate library, which is the arrangement Home Assistant's own `infrared-protocols` maintainers asked for: prove it locally, contribute it upstream once it has earned the trip.

---

## Tested and untested

Everything published here ships marked **untested by others**, carrying the fittings that came in with the wig. It graduates when independent people install it, confirm it drives their hardware, and say so.

The bar for that graduation is three complete fittings from three distinct GitHub handles. Fittings accumulate in the [Wig Shop](https://github.com/DAB-LABS/WigShop), which is also where wigs come from in the first place.

A generated integration's README carries the whole chain in plain text: which wig, which content hash, which handles fitted it and when, which HAIR version, and whether the self verification gate passed. If any of that is missing, the integration should not have been published.

---

## Prior art

The shape of this repo is copied, deliberately and with thanks, from [balloob's serial-integration-factory](https://github.com/balloob/serial-integration-factory), which does the same thing for RS232 devices. The idea that the factory is a workflow document rather than a program is his, and it is a better idea than the one we started with. The generated integrations mirror [`lg_infrared`](https://www.home-assistant.io/integrations/lg_infrared) by @abmantis, which is the reference implementation for an IR integration built on Home Assistant's `infrared` platform.

---

## License

The workflow, the scripts and the documentation in this repo are MIT. Each generated integration ships with its own MIT license file. Wig data comes from the Wig Shop under CC0.

Generated codecs are written from protocol specifications only. No code derived from GPL or LGPL implementations goes into them, which keeps the path into upstream `infrared-protocols` clean.

---

## Questions

Open an issue here for anything about the factory. Wigs and fittings live in the [Wig Shop](https://github.com/DAB-LABS/WigShop). HAIR itself has [its own tracker](https://github.com/DAB-LABS/HAIR/issues).

Thanks for proving things. 🍻
