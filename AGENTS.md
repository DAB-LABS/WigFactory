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

### What CI checks, and what it does not

`.github/workflows/ci.yml` runs ruff over `verify/` and `publish/`, the recipe
and digest parity vectors, and the real input gate over every wig the shop
publishes, on Python 3.13 and 3.14. A fourth job runs the FULL gate, codec
checks included, against every integration already built here.

**HAIR is pinned, except once a week.** `verify/HAIR_REF` names the HAIR
release the gate judges against, and it is the one place the pin lives:
`setup.sh` reads the same file. A wig should be judged by a HAIR that does
not move underneath it. The weekly scheduled run is the exception: it checks
out HAIR at `main`, so a stale pin shows up as a red X on a Monday morning
rather than as a surprise mid-publish. That run exists because of 0.9.5,
which removed `fitting_rows`: nothing went red, the gate simply started
dying on a traceback.

The pin is deliberately ours rather than the Wig Shop's. The shop pins its
own `HAIR_REF` for its own checks. Ours has to be at least 0.14.2, where HAIR
started reporting whether a decoded label accounts for its whole capture,
because the factory rebuilds codes from labels. Bump it by hand in a pull
request, one line.

**Two kinds of red, and they must never look alike.** The gate exits 1 when
it refuses a wig and 3 when it reached no verdict at all: HAIR missing or too
old, a dependency not installed, or the gate itself crashing. Our own faults
(lint, parity, a crash, a built integration failing its gate) are red on
every event. A wig on the shelf the factory cannot build from is a true
statement about somebody else's repository, so it annotates on push and pull
request and goes red only on the weekly run. Otherwise one bad wig on the
shelf would turn every pull request here red until somebody else fixed it.

That split is not decoration. From 24 August to 22 September 2026 every
weekly run died on a missing dependency (PyYAML, needed by HAIR's comb since
0.12.0) before it gated a single wig, and it looked exactly like the red X a
bad wig produces. Nobody read it.

CI does not pass `--require-handles`. The account count is reported, never
enforced, and whether a wig is proven widely enough to publish is a judgment
the owner makes at publish time.

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
Python 3.13 or later on the machine, creates `.venv`, and installs
`verify/requirements.txt`. **3.13 is a hard floor**, matching HAIR's own
`requires-python`. If setup reports no suitable interpreter, install one and
run it again; it will not guess and it will not silently skip the gate.

**Upstream `infrared-protocols` is required, not optional.** HAIR has no
local decoder for NEC, the most common consumer protocol there is, so
without upstream every NEC wig reads "does not decode to any known protocol".
That is a false statement about a good wig, and it happened: the Winix 5500
refused on 3.12 and passed on 3.14. The gate now refuses to start without
upstream rather than report an environment problem as a wig defect. The
range in `requirements.txt` is HAIR's own, and it resolves to 5.x on 3.13 and
8.x on 3.14; CI runs both, and the gate records which one it used.

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
reproducible later. Fittings accumulate over time, so an account count is a
claim about a moment; `WigShop@<sha>` is how somebody checks it a year from
now. A wig named by path carries no such record and
the gate will not invent one.

Run the gate before you look at anything else.

It enforces the hard requirements, and all of them are refusals, not
warnings:

1. **It parses** through HAIR's own `wig_format.parse_wig`. Not a lookalike
   parser you wrote. The same code the user's install runs on import.
2. **It carries at least one complete claims bundle.** Complete means one
   person claimed every row worked. A wig with no fitting is a spreadsheet,
   and this factory does not take spreadsheets.
3. **Every bundle names this wig.** Its `wig_id` has to match the wig's. A
   bundle naming another wig is not a stale attestation, it is somebody
   else's, and row digests can still line up by coincidence on a shared code
   set.
4. **Signatures verify** where a bundle carries `key` and `sig`. A bundle
   that claims a signature and fails it is a hard stop. An unsigned bundle
   passes with a note.
5. **Every signal decodes, and to one protocol family.** Mixed protocol
   wigs are out of scope: one wig, one codec. A signal that will not decode
   at all is out of scope too, because there is nothing to generate from
   raw replay.
6. **Every label accounts for its whole capture.** A codebook rebuilds each
   code from its decoded label, so a label that explains only part of what
   was captured means the integration would transmit something nobody
   fitted. HAIR 0.14.2 answers this per signal. `False` refuses. `None`
   means HAIR cannot say, usually because the decoder is upstream's, and
   that notes and does not refuse (owner ruling 2026-09-22); the forward
   and reverse checks still have to pass.
7. **No carrierless codes.** A Pronto with a `0100` header must go out
   unmodulated. Until it is established that a generated integration can
   send one that way, the gate refuses rather than ship a code that would
   go out modulated and look like it worked.
8. **No extra lattices yet.** A `hair-wig/4` matrix carries peer lattices
   for presets. Every lattice check here reads the main lattice only, so
   those codes would pass unchecked, and the gate refuses until it checks
   them too.
9. **No climate cell lands on the wrong state unanswered.** When the live
   comb says a cell sends a state other than the one on its label
   (`field-mismatch`, `duplicated-neighbour`), a climate entity built from
   it would report one state while the unit sits in another. That refuses
   unless a person's answer to that cell still stands against its current
   bytes (owner ruling 2026-09-23). Command wigs only get a note. See
   "The comb, run live".
10. **No row asks for a waveform that cannot exist.** Setting both
   `bypass_protocol` and a ditto count is a contradiction: only the encoder
   renders a repeat frame, so a bypassed row asking for one describes
   something nothing can produce.
11. **The integration reproduces the transmit recipe**, when one is being
    checked. See section 3.2.

It also **counts distinct contributors**, and this is not the same as
counting handles. The `github` field is free text somebody typed, so one
account arrives as `dab`, `@dab`, `DAB` and `github.com/dab`. The gate
compares a canonical form, counts only fittings that actually name a GitHub
account, and says out loud when two fittings collapse to one person. A
display handle names nobody a reviewer can check, so it never counts toward
the bar.

**There is no promotion bar.** The formal three-accounts rule is retired
(owner ruling 2026-08-04, following HAIR retiring it from the format on
2026-08-02), and `EXEMPTIONS.md` went with it. A rule that could be waived by
editing a file sitting beside it was never really a rule, and the waiver
machinery existed only to soften a threshold that should have been a
judgment.

What replaced it is one rule the factory holds itself, requirement 2 above:
**nothing is built without a Perfect Fit**, one person's claims covering
every row of the wig (owner ruling 2026-09-22). The Wig Shop no longer holds
that line for us. Since 2026-09-16 its shelf takes wigs with no fitting at
all, and reports a missing Perfect Fit rather than refusing it, so some wigs
on the shelf will always be refused here. That is intended: the shop keeps
files people download, and this repository builds code people install.

Once a wig clears that, the open question is how many people have proven it,
and the gate reports that number on every run rather than ruling on it.

`--require-handles N` still exists for anybody who wants a hard floor on a
particular run. It is off by default and CI does not pass it.

**What the count actually means.** One account is one person who vouched for
the whole wig. Four is four people, four units, four rooms, four blasters,
all arriving at the same answer. Nobody can fake that and no tool can
generate it. Whether it is enough to publish under the organization's name is
the owner's call at step 7, made while looking at the number, not a threshold
the gate enforces on its behalf.

### Matrix wigs

A matrix wig carries a climate block instead of, or as well as, a list
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

### The comb, run live

The gate combs every wig itself, with the pinned HAIR, on every run. A comb
receipt stored in a wig is read, reported and compared, and never taken as
the answer: it describes the HAIR that wrote it, and the file is text
anybody can edit. The Dreo fan is the case in point. Its receipt says no
suspects, and a live comb flags a frame disagreement on Oscillate
Horizontal, because that check shipped after the wig was combed.

So there are three layers, and each is labelled for what it is:

1. **The live comb**, HAIR's current opinion of these bytes, all thirteen
   check classes, plus the field tier: whether a field map read the codes,
   how many, and what they say against their labels. A lattice no map
   covers is said out loud, because "no suspects" sounds the same whether
   the payload was read or not.
2. **The stored receipt**, as history. More suspects live than stored means
   newer HAIR checks more. Fewer live than stored is what a completed repair
   looks like, and the gate says so rather than accusing it.
3. **The gate's own lattice and frame checks**, the independent second
   opinion. Where the gate and the comb disagree about a class they both
   judge, the gate says that too.

The live comb **reports**, with one exception. A Perfect Fit made in HAIR
0.14 or later could not open while a finding was open, so on a current wig
a live finding means either a newer check or an answered one. The
exception is a wrong-state finding on a climate cell that nobody has
answered: that refuses (owner ruling 2026-09-23). Answers count per cell,
as HAIR's Detangle counts them, so an answer on one cell never settles its
neighbour.

Answers a person gave to a finding without changing bytes ("use it anyway",
"keep both") ride in the receipt as attestations keyed to the bytes and the
field-map version. The gate reports whether each still matches the current
code, and never whether it was right.

Repair records (HAIR 0.14.0) are read the same way: counted by tier
(air-tested, rule-derived, accepted), carried into the generated README,
and never treated as evidence, because they sit outside every hash and
nothing signs them. A code that claims a repair and is still flagged by the
live comb is called out.

### The transmit recipe, and what a claim actually binds

`hair-wig/3` (HAIR 0.9.5, the Fitting Room) changed the model under this
factory, and the change is not cosmetic. Read this before touching anything
that reads a fitting.

**Attestation moved from the file to the row.** There used to be one
`content_hash` covering the whole signals array, and a fitting bound to it: a
match meant every signal was proven, a mismatch meant none were. Now each row
has a digest and a claim covers exactly the rows it names. Editing one code
orphans the claims about that code and leaves the rest standing.

**The digest is contract. Reproduce it, never reinvent it.**

```
row_digest = sha256(normalized_pronto + "|d<ditto_count>" + "|b<0|1>")[:16]
```

`normalized_pronto` is HAIR's validator normalization then lowercased hex.
The factory calls `wig_format.row_digest`; it does not compute this itself,
and `verify/test_recipe.py` fails if `verify_wig.py` ever imports `hashlib`,
because a second implementation of a published contract is how the contract
forks. Two things are deliberately OUT of the digest and must never be added:

- **The alias.** Names are metadata and renames are free. A claim has to
  survive one.
- **The send count.** How many times to press depends on the room, not the
  device. Two people proving the same codes at three sends and five sends are
  proving the same thing.

**The recipe lives on the signal now, not on the fitting.** Three fields:

| Field | Meaning | In the digest |
|---|---|---|
| `send_count` | send the whole blob again, after a pause | no |
| `ditto_count` | repeat frames the encoder appends inside one transmission | yes |
| `bypass_protocol` | skip the re-encode, put the raw blob on the air | yes |

`send_times_used` is gone. So is aggregating it by maximum across fitters:
there is nothing to aggregate, because the wig states the answer. If you find
a doc that still describes the old field, the doc is stale.

**The discriminator is the shape, never the version stamp.** A fitting with
`content_hash` is pre-claims; one with `wig_id` and `rows` is a claims
bundle. This matters because HAIR's own branch wrote `hair-wig/3` files
carrying old-shape fittings before the claims model landed, so trusting the
major would let those through into a model with no reader for them. Use
`wig_format.is_legacy_fitting` and `is_claims_bundle`. A matrix bundle names
its lattice binding `cells_hash` and never `content_hash`, precisely so the
test stays a single unambiguous question.

**A pre-claims fitting no longer counts toward anything.** It cannot: it says
nothing about which rows anybody walked, so counting it would mean inventing
evidence. The gate names it and moves on. Adopting the wig onto a device on
0.9.5 and saving it back to the closet brings it back.

**Coverage and the account count answer different questions.** Coverage is
how many rows anybody has proven, pooled. The count is how many distinct
people have proven ALL of them. Coverage can be 12 of 12 while nobody at all
can vouch for the whole wig, because three people each proved a different
third. The gate prints both; do not substitute one for the other.

### 3.2 The integration has to reproduce the recipe

The forward and reverse checks prove the generated encoder puts the right
IDENTITY on the air. They cannot prove it puts the right WAVEFORM on the air,
because identity is what survives decoding and the recipe is what happens
either side of it.

So a generated codebook declares `WIG_RECIPE` beside `WIG_ALIASES`, mapping
the wig's alias verbatim to `(send_count, ditto_count, bypass_protocol)`, and
the gate compares it against the wig value by value. It is optional only
while every row is plain, meaning a send count and nothing else, because
`DEFAULT_SEND_COUNT` already covers that case on its own. The moment one row
asks for a ditto or a bypass, the map is mandatory and a missing one is a
refusal.

**Refusing is the point.** Until a generator can express a ditto, the honest
outcome for a wig that needs one is a refusal naming the rows, not a
published integration that rounds the waveform off and inherits somebody's
signature while doing it.

Two repeats are at work and they are not interchangeable. The ditto is
rendered by the encoder inside one transmission at the protocol's own timing;
it is part of the waveform, it is in the digest, and it is not tunable. The
send count sends that whole transmission again after a pause; it is the
user's to change and sits outside the digest on purpose. An integration that
implements one and calls it the other is wrong in a way no codec check will
catch. Verified against upstream on 2026-08-03: the candle's vendored RC-5
encoder at `repeat_count=1` is byte-identical to `infrared-protocols`
8.2.1 (47 edges, 138003us, an 89997us inter-frame gap).

Record what the gate printed. The wig id, content hash, shop commit, fitter
handles and dates, HAIR version, send count and pooled coverage go into the
generated README in step 6, and you cannot reconstruct them later.

**If a wig fails this gate, stop and report why.** Do not repair the wig.
Corrections are the fitter's job, in HAIR, on the device: adopt it, fix it
there, save it back to the closet. In
particular, never edit a `github` value to make a count come out better: the
signature covers it, and rewriting it forges somebody's attestation.

Then copy the wig into `wigs/` per ground rule 1 and work from that copy.

---

### What the Wig Shop guarantees, and what it does not

The shop is the factory's input and its rules decide what can arrive. Three
of them matter here.

**The shelf takes unproven wigs** (shop #26, 2026-09-16). A wig for a real
device can land with no fitting and no signature. What the shelf still
guarantees is that it parses under the shop's pinned HAIR and carries a
`wig_id`, which only HAIR mints, so it has been through HAIR at least once
(the shop refuses a wig without one; #27 says so up front). And a Perfect
Fit, where one is claimed, means what it always meant: one bundle covering
every current row, never a union of several. What it no longer guarantees is
that anybody has proven the wig at all. So the factory checks that itself,
and refuses anything short of a Perfect Fit.

There is one place the shop got stricter. A replacement with no Perfect Fit
for a wig that has one is refused there, so a proven description cannot be
swapped for an unproven one without a maintainer deciding to.

**Identity is the signing key, over there.** The shop counts keys, because a
name is what somebody typed and a key is which install they typed it on. One
install has one current word: a re-fit from the same install replaces that
person's earlier bundle rather than stacking a duplicate.

The factory counts GitHub accounts instead, and that is deliberate rather
than a disagreement. The shop is asking "is this one install saying one
thing"; the factory is asking "how many checkable people". The shop's own
contributor guide says the handle exists partly so a maintainer can notice
two fittings from one person on two machines "when independence is being
counted at promotion", which is this repository's job. Two bundles, two keys,
one account is therefore ONE independent account here, counted once and said
out loud.

**Content changes arrive as supersession.** A changed wig is a NEW wig with a
new `wig_id` that names its ancestor in `supersedes`; the old file leaves the
shelf. Critically, the successor composes the same brand-kind-model filename,
so the ordinary supersession pull request is a modify at one path.

That last one has teeth for anything already published. A wig can be replaced
underneath a repository that was built from its ancestor, with the filename
unchanged, and only the `wig_id` says so. `supersedes` is recorded as a gate
fact for exactly this reason, and the update path has to compare it against
what the published integration was built from rather than assuming a
filename means what it used to.

### Filenames carry a tier suffix. It is not part of the device.

HAIR names a download `<brand>-<kind>-<model>-perfect-fit.wig.json`, and that
is what lands in the shop. The suffix records what the fitting looked like at
the moment of download.

**It must never reach a repository name or a domain.** The shop itself never
reads a tier from a filename, because a name that could promote a file by
being edited would defeat the point of signed per-row claims. Here the reason
is different and just as firm: a repository name, a domain, a config entry
and a device registry entry are all permanent, and baking a transient label
into them means somebody's install carries it forever.

So the repository is `<brand>-<kind>-<model>-ir` and the tier is stripped:
`fable-fan-ft-9000-perfect-fit.wig.json` publishes as `fable-fan-ft-9000-ir`.
`verify_wig.device_stem` owns the stripping and `TIER_SUFFIXES` owns the
list. Either spelling resolves a wig on the command line, so you can name the
device rather than remember which suffix the file landed with.

**The `<kind>` in a repository name is HAIR's word, not the file's.** HAIR
0.16 turned kind into a fixed list of twenty-six words plus `other`, and it
reads a few known spellings as list words at display time without rewriting
any file: `airconditioner` reads as `ac`. The factory names by the same rule,
through HAIR's own `normalize_kind`, so a Komeco AC filed as
`airconditioner` still becomes `komeco-ac-...-ir`. A name is permanent; a
spelling in somebody's file is not. (Adopted 2026-09-22. The publish tool still
names from the filename stem, and does not yet apply this; it has to before
the first AC publishes.)

### Where a wig comes from, and why the factory never repairs one

HAIR 0.9.5 moved fitting out of the closet and onto the device, and 0.14.0
(Detangle) moved repair there too. Both matter here because they decide what
arrives and what this repository is allowed to do about it.

Somebody adopts a wig onto a device and lives with it. The device is the
workbench: test a command, rename it, re-capture a bad code, tune sends and
dittos. When it works they save it to the closet, tick the rows they are
willing to vouch for, and sign. That signature is the claim, and the wig is a
snapshot of what was working at that moment.

**Combing and fitting used to be orthogonal. They are coupled now.** A claim
proves a person pointed a blaster and a device answered. A comb proves the
other several hundred codes are coherent with each other, and since 0.12.0
that each code says what its label says, read against a field map. Since
0.14.0 a Perfect Fit will not open on a device while any comb finding is
open: every finding has to be fixed, or answered by a person, first.

That coupling is only as strong as the HAIR that did the fitting. A wig
fitted before a check existed carries a Perfect Fit and a comb receipt that
never ran that check, which is exactly the Dreo fan: its stored receipt says
no suspects, and a live comb with current HAIR flags Oscillate Horizontal. So
the gate never takes a stored receipt as the answer.

**How a defect gets fixed, and it is not here.** The comb flags a code and
the device shows it under Needs attention, one row per finding with a plain
reason. The person fixes it there: accepts bytes that already exist in the
file, or a frame HAIR synthesized under a ratified field-map rule from one
real press (checked by reading it back before it is offered), or listens to
the real remote, or pastes a code. Flagged matrix cells stay in the matrix
and are fixed in place; they are no longer pulled out as separate command
rows. A fix writes back to the closet as a repaired copy of the wig, with a
repair record on each mended code, and a person can instead answer a finding
without changing bytes ("use it anyway", "keep both"), which is recorded as
an attestation in the comb receipt.

Neither a repair record nor an attestation is signed by anything. They ride
outside every hash on purpose, so they are the file's word about itself,
exactly as the comb receipt is.

So the factory's job when a wig fails the gate is to **say what is wrong and
stop**. Never repair a wig here. A repaired wig arrives already repaired,
and the gate should recognize that rather than accuse it: a comb receipt
recording suspects that are no longer present is what success looks like,
and the gate says so.

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

- They are mutable. Nothing about a claim covers them: a row digest is
  `pronto`, `ditto_count` and `bypass_protocol`, so brand and model can be
  corrected without invalidating a single claim. The filename cannot drift,
  because under the shop's immutability rule a rename is a new file.
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

**Send count against the wig.** `DEFAULT_SEND_COUNT` in the generated
`const.py`, read out of the file rather than imported, against the highest
`send_count` the wig states. Below it is a refusal. Above it is allowed and
noted, since more frames cost airtime and not correctness. This check is not
about the codec at all: a codec can be perfectly right and the integration
still look broken, because the frames never arrived.

**Recipe conformance.** `WIG_RECIPE` in the generated `codes.py` against the
wig, row by row. Mandatory the moment any row asks for a ditto or a bypass,
optional while every row is plain. Section 3.2 has the reasoning; the short
version is that the digest a fitter signed covers the ditto count and the
bypass flag, so an integration that drops either one ships a waveform nobody
attested while every codec check still reads green.

If you touch the recipe reader or anything near the digest, re-run the
vectors:

```bash
.venv/bin/python verify/test_recipe.py
```

It pins the published digest layout against hand-computed vectors, proves
both exclusions by demonstration (a rename and a send-count change must not
move a digest, a ditto and a bypass must), checks the reader's clamping, and
fails if `verify_wig.py` has grown a local `hashlib` import. That last one is
the real point: the factory calls HAIR's `row_digest` and must keep calling
it, because a second implementation of a published contract does not fail
loudly, it just quietly decides valid attestations do not match.

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

**Frames per press comes from the wig, not from you.** Real remotes do not
send one frame. RC-5 re-sends the same code every 114ms for as long as the key
is held, so a physical press is three or four frames, and a battery powered
device that duty cycles its receiver can sleep straight through a single
frame. The symptom is a button that works on the first press sometimes and
needs three other times, with no pattern, on a codebook that is completely
correct. The codec checks cannot see it, because encoding and decoding are
both fine. So:

- `const.py` carries `DEFAULT_SEND_COUNT`, `MIN_SEND_COUNT = 1`,
  `MAX_SEND_COUNT = 10` and a gap between frames of about 100ms.
- `DEFAULT_SEND_COUNT` is the **highest `send_count` the wig states**, which
  is the number the gate prints. Not a number you chose. The gate refuses a
  default below it, because shipping under it reproduces a fault somebody
  already found and wrote down.
- All the frames in one press share one RC-5 toggle value, and the toggle
  advances once, after the last of them. A press is one press. Advancing per
  frame tells the device it was pressed three times, which is exactly what
  toggle exists to distinguish.
- Expose it in the options flow. A send count is about a room, and the next
  person's room is not this one. This is the ONLY one of the three recipe
  fields that is the user's to change, which is exactly why it is the one
  left out of the row digest.
- **The ditto is not this.** `ditto_count` is rendered by the encoder inside
  a single transmission, it is in the digest, and it is not tunable. Carry it
  into the command's `repeat_count` and declare it in `WIG_RECIPE`. An
  integration that implements a ditto as an extra send count, or the reverse,
  is wrong in a way no codec check will catch.
- **When rows disagree** on send count, a single knob cannot express it. Ship
  the highest, and say in the README which rows wanted less. The gate prints
  the spread.

**Requirements are PyPI specifiers only.** Never a VCS URL: hassfest and
HACS both pass it and the config flow then fails with a 500 at runtime, which
is a miserable afternoon. Never a space around the `@` in a requirement
string either.

Write tests alongside. Round trip every codebook entry through encode and
decode, assert the vendored decoder agrees with HAIR on every wig signal, and
mock every connection.

### 5.1 A climate integration

A matrix wig does not become a codebook. There is nothing to encode: every
state the unit can be in was captured as a complete code, and the integration
replays the one that matches. The rulings behind the shape are in
`docs/plans/climate-build-path.md`. What that means on disk:

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

The details that are not obvious:

- **`lattice.json` is copied, never rebuilt.** `{"format": "hair-matrix/1",
  "wig": {..., "wig_id": ...}, "climate": <the wig's climate block>}`. The
  gate compares the climate block to the wig's field for field and refuses
  any difference. One cell per line keeps a diff readable.
- **Resolution is HAIR's, vendored.** `lattice.py` carries a trimmed copy of
  `wig_climate.resolve_cell` and a `Resolver.resolve(hvac_mode, fan_mode,
  swing_mode, temperature)` that the entity calls for every send. The gate
  calls the same method for every state the entity offers, plus off-grid and
  out-of-range temperatures, and requires HAIR's answer every time.
- **The entity's words are Home Assistant's; the lattice's stay verbatim.**
  `FAN_MODES`, `HVAC_MODES` and `SWING_MODES` map one onto the other, one to
  one, in the wig's order. Fan words have to be valid translation keys (no
  `+`), and each needs an English name in `translations/en.json`. Where core
  already has a word, use it: `medium_low` and `medium_high` are what
  `lg_infrared` uses.
- **Every send ends on HAIR's 50 ms terminator** (GH #98). Broadlink RM4 Pro
  firmware garbles a stream that ends on a mark, and the 200 ms capture
  silence at the end of every Pronto overflows a 16-bit emitter. The gate
  checks every code converts to exactly
  `TerminatedCommand(ProntoCommand(code))`'s timings. Do not depend on
  upstream's `ProntoCommand`: it only exists from infrared-protocols 8.x.
- **`lattice.py` and `command.py` import nothing from Home Assistant.** That
  is what lets the gate import them. Anything the entity decides about which
  code to send belongs in them, not in `climate.py`.
- **A change sends the whole state.** Off sends the Off code. Changing fan,
  swing or temperature while off only records it, and the next Turn on sends
  it. The entity shows the cell that went out, not the request, and only
  after the send returned.
- **Restore from the entity's own stored data, never from state
  attributes.** Home Assistant converts attributes to the installation's
  unit system, so on an imperial install a saved target of 86 reads back as
  86 degrees Celsius. Keep the assumed state in `extra_restore_state_data`,
  in Celsius and the entity's own words. Found on the test box, which runs
  imperial.

The gate runs these checks when it finds a `lattice.json` beside a
`lattice.py`, instead of the codebook ones.

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
- Every fitter: handle, GitHub handle, date, how many rows they claimed, and
  the signing key fingerprint. Print handles as the fitter typed them. They
  are compared canonically and displayed verbatim, never rewritten.
- The independent-account count, as a number rather than a verdict.
- **Pooled row coverage**, which is a different number from the account
  count and is worth stating beside it. "12 of 12 rows proven, by 1 account
  of 3" says something true that neither number says alone.
- **Frames per press, and where the number came from.** Say it is what the
  wig states, and say what to do if presses still get dropped, because that
  is the single most likely thing to need adjusting on hardware other than
  the bench set. A reader who knows the number came from somebody's bench
  will reach for the setting instead of filing a bug.
- **The ditto count, if any row has one**, and that it is not adjustable.
  Somebody who finds the send-count setting will otherwise assume it is the
  only repeat in play.
- That the codebook was machine verified against HAIR's independent
  decoders, and in which directions.
- **What the live comb said**, with which HAIR, and on a lattice which field
  map read how many codes. `provenance_lines()` writes it.
- **How many codes the wig says were repaired, by tier**, when any were.
  Say it is the wig's own statement: repair records are signed by nothing.
- Installation, the entities it creates, and what to do when a code does
  not work.

House style from rule 6 applies. These are public files.

---

## 7. Publish, and only when the owner says so

Gates, all of them, before anything is pushed:

- Step 4 green in both directions.
- The input gate's fitting evidence real and recorded in the README.
- **The account count read, and your ruling on it.** There is no threshold;
  publishing under the organization's name is a decision, and this is the
  moment it gets made.
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

1. **Re-runs the gate itself**, full, against the tree as it stands. Anything
   short of a pass stops everything. This is load bearing: a green run from
   earlier proves nothing about the tree now, so publication is gated by
   construction rather than by whoever remembered. It does not pass
   `--require-handles`; the account count reaches the owner as a number in
   the report, at the moment they are deciding whether to push.
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

**Updating a published integration is a different command.** More people
claim a wig; the shop publishes a successor with a new `wig_id` at the same
filename; the send count moves; the stamp goes stale. That happens far more
often than a first publish, so it is automated too:

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

Independent fittings from distinct GitHub handles, on the shipped
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
