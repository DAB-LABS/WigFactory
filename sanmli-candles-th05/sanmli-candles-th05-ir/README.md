# Sanmli TH-05 Candles

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DAB-LABS&repository=sanmli-candles-th05-ir&category=integration)

Home Assistant control for a set of infrared LED tea light candles, over any infrared blaster Home Assistant can already talk to.

**Status: untested by others.** It has one recorded fitting, from the person who captured the codes. Nobody else has confirmed it on their own hardware yet. If you install it and it drives your candles, please say so in an issue, because that is the only thing that moves it out of this state.

---

## The device

Flameless LED tea lights sold in a set with a small infrared remote, bought on Amazon.

**Manufacturer per the Amazon listing: Sanmli.** The OEM has not been independently established. Marketplace goods like these usually trace back to one factory selling under many brand names, so treat the brand as the name on the box rather than a claim about who built it. If your candles look identical under a different logo, this integration will very likely drive them: the codes carry RC-5 system address `0x1F`, and rebadged units from one maker normally keep the address whatever the logo says.

Identifiers, in case yours is the same hardware wearing a different name:

| | |
|---|---|
| ASIN | B0DF7FPV55 |
| UPC | 794969274724 |
| Protocol | RC-5, address `0x1F`, 36 kHz |

---

## What you get

**A light.** On, off, and four effects: Candle, Flicker, Fade out, Solid.

**Twelve buttons**, one per button on the physical remote, including the two brightness steps and the four sleep timers.

**An event entity**, if you have an infrared receiver. It fires when somebody picks up the handheld remote, so an automation can follow along. That is what the receiver picker during setup is for: the emitter is how Home Assistant talks to the candles, the receiver is how it listens to the handheld. Skip it and you simply get no event entity.

### Frames per press

Each command transmits four times by default, about a tenth of a second apart. That is a setting, under the integration's Configure.

A press on the handheld remote is not one transmission. RC-5 re-sends the same code every 114ms for as long as you hold the key, so a real press is three or four frames. These candles appear to sample their infrared receiver on a duty cycle to save battery, which means a single frame can arrive while the receiver is asleep and be missed completely. On the bench that looked like a button working on the first press sometimes and needing three presses other times, with no pattern.

Repeating the frame fixed it. If presses still get dropped, raise it. If one is plenty for your set, lower it and save the airtime.

Where the number came from: the fitting. Four is the highest number of sends any fitter needed, across one fitting that records it. It is a measurement of somebody's room rather than a guess, which is why the number to reach for when presses get dropped is this one. Three worked too on the bench set; the default follows the evidence rather than the smallest number that happened to work.

### Why there is no brightness slider

The remote has Brighten Up and Dim Down. They are relative steps: no absolute levels, no feedback, and no published step count.

Home Assistant's brightness contract is absolute, so exposing a slider would mean reporting a number nobody measured. Press dim when the candles are already at their floor, or use the handheld remote once, and the number in Home Assistant quietly stops matching the room, with no way to notice or resync.

So the steps are buttons, where a press means a press, and the light reports only what it can honestly know. That is the same reason the light is marked as an assumed state device: infrared is one way, and nothing here can see whether the candles actually lit.

---

## Installing

**Through HACS.** Use the badge above, or add `https://github.com/DAB-LABS/sanmli-candles-th05-ir` as a custom repository of type Integration, then install and restart.

**By hand.** Copy `custom_components/sanmli_th05_ir` into your `config/custom_components/` and restart.

Then add the integration from **Settings, Devices and services, Add integration**, and pick the infrared emitter that can reach the candles. A receiver is optional; without one you simply get no event entity.

You need an infrared emitter already set up in Home Assistant on the `infrared` platform. ESPHome, Broadlink and Tuya devices all work.

---

## Where the codes came from

Every code here was captured off the physical remote with [HAIR](https://github.com/DAB-LABS/HAIR), then proven on the real candles signal by signal before anything was generated.

| | |
|---|---|
| Source wig | [`sanmli-candles-th05.wig.json`](https://github.com/DAB-LABS/WigShop/blob/main/wigs/sanmli/sanmli-candles-th05.wig.json) |
| Wig Shop commit | `7197993` |
| Content hash | `sha256:50e076e9623326a4eb9a500572c20d98296f840cccf8f4caadce6314dafd2731` |
| Generated by | [WigFactory](https://github.com/DAB-LABS/WigFactory) |
| Verified against | HAIR 0.9.0 decoders |
| Combed | 2026-07-31, no suspects |

### Fittings

A fitting is a per signal record that somebody pointed a blaster at the real device, pressed every button, and marked each one as working.

| Fitter | GitHub | Date | HAIR | Sends needed | Signed |
|---|---|---|---|---:|---|
| David | [@DAB-LABS](https://github.com/DAB-LABS) | 2026-07-31 | 0.9.1 | 4 | key `c821d7fff5adfa5c` |

**1 of 3 distinct accounts.** Three fittings from three different people promotes this from untested to tested. The signature proves the record has not been altered since it was made on that install. It does not prove identity, and it is not meant to.

### How the codebook was checked

The codebook was not eyeballed. It was checked by machine against HAIR's own protocol decoders, which never saw the generated code, in both directions:

- **Forward.** Each generated code is encoded, then decoded by HAIR. The identity read back matches the identity HAIR reads from the captured signal. 12 of 12.
- **Reverse.** Each captured signal is decoded by the decoder vendored into this integration. Same identity again. 12 of 12.
- **Coverage.** Every captured signal maps to exactly one code, and every code traces back to exactly one captured signal. No dropped buttons, no invented ones.

The RC-5 toggle bit is excluded from all of this, because it records which press a signal was rather than which button.

---

## The codebook

| Button | Remote label | RC-5 command |
|---|---|---|
| On | On | `0x01` |
| Off | Off | `0x08` |
| Flicker effect | FL | `0x02` |
| Fade out effect | BL | `0x06` |
| Candle effect | SL | `0x0C` |
| Solid light | Light | `0x0E` |
| Brighten | Brighten Up | `0x0B` |
| Dim | Dim Down | `0x0A` |
| 2 hour timer | 2 Hour | `0x10` |
| 4 hour timer | 4 Hour | `0x04` |
| 6 hour timer | 6 Hour | `0x20` |
| 8 hour timer | 8 Hour | `0x12` |

---

## When something does not work

**Nothing responds at all.** Check the blaster has line of sight; infrared will not go round a corner or through a sofa. Try the buttons before the light, since a button is one code and nothing else.

**Presses are sometimes ignored.** Raise **Frames per press** under Configure. See the section above; this is the single most likely thing to need adjusting on hardware other than the bench set.

**Some buttons work and others never do.** That is worth an issue, and it means something different from the above: a code that never works was probably captured cleanly but wants different treatment from its neighbours.

**It works on candles that are not Sanmli.** Also worth an issue, and genuinely useful: it tells everyone the same hardware ships under more than one name. Include whatever brand is on your box.

**The event entity never fires.** It only exists if you selected a receiver during setup. Check the integration's options, and check the receiver hears the remote at all.

---

## License

MIT, see [LICENSE](LICENSE). The IR codes themselves come from the [Wig Shop](https://github.com/DAB-LABS/WigShop) under CC0.

The RC-5 codec in `decoder.py` is written from the protocol specification. No part of it derives from a GPL or LGPL implementation, which keeps the door open to contributing it to Home Assistant's own `infrared-protocols` library one day.
