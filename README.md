# WigFactory

Turns a proven wig into an installable Home Assistant integration.

A **wig** is one JSON file holding one remote's codes, captured with [HAIR](https://github.com/DAB-LABS/HAIR). This repo is the workshop where a wig becomes a real integration: a codebook, entities, a config flow, and a repository of its own with a HACS badge.

**This is not a program.** It is a workflow that an AI coding agent follows. The factory is [`AGENTS.md`](AGENTS.md). You clone this repo, open a coding agent in the folder, hand it a wig, and it builds.

---

## Why a wig and not a code database

Anyone can generate an integration from a table of IR codes. The interesting question is whether the result actually drives the hardware, and a table cannot answer that.

A wig can. Every wig that enters this factory is a **perfect fit**: somebody adopted it onto a real device, lived with it, and then claimed that every row of it worked on their own hardware. Each claim is bound to a digest of the exact signal it covers, including the repeat count and protocol handling that signal is sent with, and signed by the install that recorded it. Change a code afterward and its digest stops matching the claim that covered it.

So the factory starts from evidence rather than from a spreadsheet. That is the whole premise.

---

## Using it

You need Python 3.12 or newer, git, and a coding agent you can run in a folder.

```bash
git clone https://github.com/DAB-LABS/WigFactory.git
cd WigFactory
./setup.sh
```

`setup.sh` shallow clones the reference repositories into `reference/`, which is gitignored. They are read only. Nothing in the build ever edits them.

That includes the [Wig Shop](https://github.com/DAB-LABS/WigShop), so the wigs are already there when setup finishes. **Nothing updates itself.** There is no timer and no daemon: you run `setup.sh`, every clone is fetched and reset to its remote, and then it all sits still until you run it again. Builds have to be reproducible, and a reference that moved halfway through is a build you cannot explain afterwards. Run it when you start, and again before any build you intend to publish.

Then open your coding agent in the repo root and hand it a wig by name:

> Build an integration from `sanmli-candles-th05`.

Files in the shop are named `<brand>-<kind>-<model>-perfect-fit.wig.json`. That suffix describes the file, not the device, so either spelling finds the wig and neither reaches the repository name: `fable-fan-ft-9000-perfect-fit.wig.json` publishes as `fable-fan-ft-9000-ir`.

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

It also counts contributors rather than strings. The GitHub handle on a claim is free text somebody typed, so one account shows up as `dab`, `@dab`, `DAB` and `github.com/dab`. Compared raw, one person on two installs reads as two people without meaning to deceive anyone. The gate compares a canonical form, counts only claims that name a checkable account, and says plainly when two collapse to one person.

That count is reported and never enforced. The shop has already established that the wig works for somebody, so the only question left is how many people, and that is a judgment at publish time rather than a threshold in a script.

```bash
python3 verify/verify_wig.py \
  --wig sanmli-candles-th05 \
  --integration sanmli-candles-th05/sanmli-candles-th05-ir
```

---

## What comes out

```
sanmli-candles-th05/
  sanmli-candles-th05-ir/     ready to push to its own repository
    custom_components/sanmli_th05_ir/
      codes.py                      the codebook, generated from the wig
      button.py  light.py  event.py
      config_flow.py  entity.py  const.py  __init__.py
      manifest.json  translations/en.json
    hacs.json  README.md  LICENSE
    .github/workflows/
```

One integration per device. The codebook is vendored inside it rather than published as a separate library, which is the arrangement Home Assistant's own `infrared-protocols` maintainers asked for: prove it locally, contribute it upstream once it has earned the trip.

---

## What the shop guarantees, and what it does not

The [Wig Shop](https://github.com/DAB-LABS/WigShop) shelf admits perfect fits only. A wig lands when at least one person has claimed every row of it worked on their own hardware, so anything arriving here is already proven by somebody. What the shelf does not say is how many people, on how many units, in how many rooms. That is the number the factory reports.

So everything published here ships marked **untested by others**, carrying the claims that came in with the wig. It earns a stronger statement when independent people install it, confirm it drives their hardware, and record that back in the shop.

**A changed wig is a new wig.** The shop does not edit codes in place. A correction arrives as a fresh `wig_id` that names its ancestor in `supersedes`, and the file it replaces leaves the shelf under the same name. A published integration can therefore be built from a wig that no longer exists, with the filename unchanged, and only the id says so.

A generated integration's README carries the whole chain in plain text: which wig, which `wig_id`, what that id supersedes, which accounts claimed it and when, which HAIR version, and whether the self verification gate passed. If any of that is missing, the integration should not have been published.

---

## Prior art

The shape of this repo is copied, deliberately and with thanks, from [balloob's serial-integration-factory](https://github.com/balloob/serial-integration-factory), which does the same thing for RS232 devices. The idea that the factory is a workflow document rather than a program is his, and it is a better idea than the one we started with. The generated integrations mirror [`lg_infrared`](https://www.home-assistant.io/integrations/lg_infrared) by @abmantis, which is the reference implementation for an IR integration built on Home Assistant's `infrared` platform.

---

## License

The workflow, the scripts and the documentation in this repo are MIT. Each generated integration ships with its own MIT license file. Wig data comes from the Wig Shop under CC0.

Generated codecs are written from protocol specifications only. No code derived from GPL or LGPL implementations goes into them, which keeps the path into upstream `infrared-protocols` clean.

---

## Questions

Open an issue here for anything about the factory. Wigs and the claims made about them live in the [Wig Shop](https://github.com/DAB-LABS/WigShop). HAIR itself has [its own tracker](https://github.com/DAB-LABS/HAIR/issues).

Thanks for proving things. 🍻
