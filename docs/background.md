# WigFactory: why the runbook says what it says

[`AGENTS.md`](../AGENTS.md) is the procedure: what to run, in what order,
what counts as passing, and who decides. This page is the reasoning behind
it and the history that produced it. The sections follow the same order as
the pipeline, and each stage in the runbook links to its section here.

Read this before you change a rule. You do not need it to follow one.

---

## CI: two workflows, two questions

**`ci.yml` asks whether the factory is broken.** Red there always means work
in this repository: our code broke, or a built integration no longer matches
its wig (the wig changed, or left the shelf), which `update_integration.py`
resolves.

**`shelf.yml` asks what the factory could build, and never goes red because
of a wig.** A wig the factory cannot build from is a fact about somebody
else's repository, and until 2026-10-13 it turned the weekly run red for
months for wigs nobody here could fix (the 2026-08-17 weekly-red ruling,
reversed by the owner on 2026-10-13).

**HAIR is pinned, except once a week.** `verify/HAIR_REF` names the HAIR
release the gate judges against, and it is the one place the pin lives:
`setup.sh` and `shelf.yml` read the same file. The weekly `ci.yml` run is
the exception: it runs the tests and the built-integration check against
HAIR `main`, so a change in HAIR that the factory has to adapt to shows up
as a red X before anybody bumps the pin, rather than mid-publish. That run
exists because of 0.9.5, which removed `fitting_rows`: nothing went red, the
gate simply started dying on a traceback.

The pin is deliberately ours rather than the Wig Shop's. It has to be at
least 0.14.2, where HAIR started reporting whether a decoded label accounts
for its whole capture, because the factory rebuilds codes from labels.

**Two kinds of red, and they must never look alike.** The gate exits 1 for a
refusal and 3 for no verdict, and that split is not decoration. From 24
August to 22 September 2026 every weekly run died on a missing dependency
(PyYAML, needed by HAIR's comb since 0.12.0) before it gated a single wig,
and it looked exactly like the red X a bad wig produced. Nobody read it.

---

## Set up

**Upstream `infrared-protocols` is required, not optional.** HAIR has no
local decoder for NEC, the most common consumer protocol there is, so
without upstream every NEC wig reads "does not decode to any known
protocol". That is a false statement about a good wig, and it happened: the
Winix 5500 refused on 3.12 and passed on 3.14. The gate now refuses to start
without upstream rather than report an environment problem as a wig defect.
The range in `requirements.txt` is HAIR's own, and it resolves to 5.x on
3.13 and 8.x or later on 3.14; CI runs both, and the gate records which one
it used.

**`setup.sh` never runs itself.** There is no timer, no daemon and no
auto-update. That is deliberate: a build has to be reproducible, and a
reference that moved underneath you halfway through is a build you cannot
explain afterwards. A stale Wig Shop clone is missing fittings that landed
since, which does not make the build wrong, only narrower than it needed to
be.

**Why `.venv/bin/python`, always.** These scripts run the gate in process,
and the gate needs what `verify/requirements.txt` installs. They are not
marked executable on purpose: a shebang cannot portably point at a relative
virtual environment, so a directly executed script would find the system
interpreter and fail somewhere less obvious than the first line.

---

## Gating a wig

### Why the slug, not the path

The slug reads the merged file every contributor sees, and it records the
shop commit, which is what makes the fitting evidence reproducible later.
Fittings accumulate over time, so an account count is a claim about a
moment; `WigShop@<sha>` is how somebody checks it a year from now. A wig
named by path carries no such record and the gate will not invent one.

### Counting people, not strings

The `github` field is free text somebody typed, so one account arrives as
`dab`, `@dab`, `DAB` and `github.com/dab`. The gate compares a canonical
form, counts only fittings that actually name a GitHub account, and says out
loud when two fittings collapse to one person. A display handle names nobody
a reviewer can check, so it never counts toward the bar.

**There is no promotion bar.** The formal three-accounts rule is retired
(owner ruling 2026-08-04, following HAIR retiring it from the format on
2026-08-02), and `EXEMPTIONS.md` went with it. A rule that could be waived
by editing a file sitting beside it was never really a rule, and the waiver
machinery existed only to soften a threshold that should have been a
judgment.

What replaced it is one rule the factory holds itself: **nothing is built
without a Perfect Fit**, one person's claims covering every row of the wig
(owner ruling 2026-09-22). The Wig Shop no longer holds that line for us.
Since 2026-09-16 its shelf takes wigs with no fitting at all, and reports a
missing Perfect Fit rather than refusing it, so some wigs on the shelf will
always be refused here. That is intended: the shop keeps files people
download, and this repository builds code people install.

Once a wig clears that, the open question is how many people have proven it,
and the gate reports that number on every run rather than ruling on it.

**What the count actually means.** One account is one person who vouched for
the whole wig. Four is four people, four units, four rooms, four blasters,
all arriving at the same answer. Nobody can fake that and no tool can
generate it. Whether it is enough to publish under the organization's name
is the owner's call at publish time, made while looking at the number, not a
threshold the gate enforces on its behalf.

### Matrix wigs

A matrix wig carries a climate block instead of, or as well as, a list of
signals: a lattice of cells, one per complete device state. There is no
codebook to build a second implementation of, so the checks are about the
lattice contradicting itself, and on real files they find plenty.

**Completeness is judged mode by mode** because a real unit does not offer
every setting in every mode: a dry mode often runs at one fan speed and one
temperature. A hole inside a mode refuses because Home Assistant would offer
it and it would silently do nothing. Until 2026-10-13 the gate demanded the
full cross product of every mode, fan, swing and temperature, and called the
Komeco KOS-09QC 526 cells short while HAIR found nothing missing.

**Collapsed rows are a feature, not a fault.** A row where every temperature
sends one code means the device ignores temperature there. Daikin does it in
19 rows of 40.

**Partial collapse is a defect.** On real files it is always a neighbour: 18
carrying 19's frame.

**Celsius is asserted, not assumed,** because a Fahrenheit lattice read as
Celsius is a silent thirty degree error.

Fittings on a matrix wig attest the dimension checklist, not the whole
lattice, because nobody fits 960 cells.

**The microscope** (`verify/derive_fields.py`) finds the bits that move
between cells: on Gree that is 15 moving bits out of 66; on Panasonic, 18
out of 216. The tool exists so you apply your judgement to a field map
rather than to 63KB of hex.

### The comb, run live

A comb receipt stored in a wig is read, reported and compared, and never
taken as the answer: it describes the HAIR that wrote it, and the file is
text anybody can edit. The Dreo fan is the case in point. Its receipt says
no suspects, and a live comb flags a frame disagreement on Oscillate
Horizontal, because that check shipped after the wig was combed.

So there are three layers, and each is labelled for what it is:

1. **The live comb**, HAIR's current opinion of these bytes, all thirteen
   check classes, plus the field tier: whether a field map read the codes,
   how many, and what they say against their labels. A lattice no map covers
   is said out loud, because "no suspects" sounds the same whether the
   payload was read or not.
2. **The stored receipt**, as history. More suspects live than stored means
   newer HAIR checks more. Fewer live than stored is what a completed repair
   looks like, and the gate says so rather than accusing it.
3. **The gate's own lattice and frame checks**, the independent second
   opinion. Where the gate and the comb disagree about a class they both
   judge, the gate says that too.

Why the live comb only reports: a Perfect Fit made in HAIR 0.14 or later
could not open while a finding was open, so on a current wig a live finding
means either a newer check or an answered one. The exception, a wrong-state
finding on an unanswered climate cell, refuses because a climate entity
built from it would report one state while the unit sits in another (owner
ruling 2026-09-23).

Answers a person gave to a finding without changing bytes ("use it anyway",
"keep both") ride in the receipt as attestations keyed to the bytes and the
field-map version. The gate reports whether each still matches the current
code, and never whether it was right.

Repair records (HAIR 0.14.0) are counted by tier (air-tested, rule-derived,
accepted), carried into the generated README, and never treated as evidence,
because they sit outside every hash and nothing signs them. A code that
claims a repair and is still flagged by the live comb is called out.

### The transmit recipe, and what a claim actually binds

`hair-wig/3` (HAIR 0.9.5, the Fitting Room) changed the model under this
factory, and the change is not cosmetic. Read this before touching anything
that reads a fitting.

**Attestation moved from the file to the row.** There used to be one
`content_hash` covering the whole signals array, and a fitting bound to it:
a match meant every signal was proven, a mismatch meant none were. Now each
row has a digest and a claim covers exactly the rows it names. Editing one
code orphans the claims about that code and leaves the rest standing.

**The digest is contract.** The factory calls `wig_format.row_digest` and
does not compute it itself, because a second implementation of a published
contract is how the contract forks. It does not fail loudly, it just quietly
decides valid attestations do not match. Two things are deliberately out of
the digest:

- **The alias.** Names are metadata and renames are free. A claim has to
  survive one.
- **The send count.** How many times to press depends on the room, not the
  device. Two people proving the same codes at three sends and five sends
  are proving the same thing.

**The recipe lives on the signal now, not on the fitting.**
`send_times_used` is gone. So is aggregating it by maximum across fitters:
there is nothing to aggregate, because the wig states the answer. If you
find a doc that still describes the old field, the doc is stale.

**The discriminator is the shape, never the version stamp.** This matters
because HAIR's own branch wrote `hair-wig/3` files carrying old-shape
fittings before the claims model landed, so trusting the major would let
those through into a model with no reader for them. A matrix bundle names
its lattice binding `cells_hash` and never `content_hash`, precisely so the
test stays a single unambiguous question.

**A pre-claims fitting no longer counts toward anything.** It cannot: it
says nothing about which rows anybody walked, so counting it would mean
inventing evidence. Adopting the wig onto a device on 0.9.5 and saving it
back to the closet brings it back.

**Coverage and the account count answer different questions.** Coverage is
how many rows anybody has proven, pooled. The count is how many distinct
people have proven ALL of them. Coverage can be 12 of 12 while nobody at all
can vouch for the whole wig, because three people each proved a different
third.

### Why the integration has to reproduce the recipe

The forward and reverse checks prove the generated encoder puts the right
IDENTITY on the air. They cannot prove it puts the right WAVEFORM on the
air, because identity is what survives decoding and the recipe is what
happens either side of it. The digest a fitter signed covers the ditto count
and the bypass flag, so an integration that drops either one ships a
waveform nobody attested while every codec check still reads green.

**Refusing is the point.** Until a generator can express a ditto, the honest
outcome for a wig that needs one is a refusal naming the rows, not a
published integration that rounds the waveform off and inherits somebody's
signature while doing it.

Two repeats are at work and they are not interchangeable. The ditto is
rendered by the encoder inside one transmission at the protocol's own
timing; it is part of the waveform, it is in the digest, and it is not
tunable. The send count sends that whole transmission again after a pause;
it is the user's to change and sits outside the digest on purpose. An
integration that implements one and calls it the other is wrong in a way no
codec check will catch. Verified against upstream on 2026-08-03: the
candle's vendored RC-5 encoder at `repeat_count=1` is byte-identical to
`infrared-protocols` 8.2.1 (47 edges, 138003us, an 89997us inter-frame gap).

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
counted at promotion", which is this repository's job. Two bundles, two
keys, one account is therefore ONE independent account here, counted once
and said out loud.

**Content changes arrive as supersession.** A changed wig is a NEW wig with
a new `wig_id` that names its ancestor in `supersedes`; the old file leaves
the shelf. Critically, the successor composes the same brand-kind-model
filename, so the ordinary supersession pull request is a modify at one path.

That last one has teeth for anything already published. A wig can be
replaced underneath a repository that was built from its ancestor, with the
filename unchanged, and only the `wig_id` says so. `supersedes` is recorded
as a gate fact for exactly this reason, and the update path has to compare
it against what the published integration was built from rather than
assuming a filename means what it used to.

### Where a wig comes from, and why the factory never repairs one

HAIR 0.9.5 moved fitting out of the closet and onto the device, and 0.14.0
(Detangle) moved repair there too. Both matter here because they decide what
arrives and what this repository is allowed to do about it.

Somebody adopts a wig onto a device and lives with it. The device is the
workbench: test a command, rename it, re-capture a bad code, tune sends and
dittos. When it works they save it to the closet, tick the rows they are
willing to vouch for, and sign. That signature is the claim, and the wig is
a snapshot of what was working at that moment.

**Combing and fitting used to be orthogonal. They are coupled now.** A claim
proves a person pointed a blaster and a device answered. A comb proves the
other several hundred codes are coherent with each other, and since 0.12.0
that each code says what its label says, read against a field map. Since
0.14.0 a Perfect Fit will not open on a device while any comb finding is
open: every finding has to be fixed, or answered by a person, first.

That coupling is only as strong as the HAIR that did the fitting. A wig
fitted before a check existed carries a Perfect Fit and a comb receipt that
never ran that check, which is exactly the Dreo fan. So the gate never takes
a stored receipt as the answer.

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

A repaired wig arrives already repaired, and the gate should recognize that
rather than accuse it: a comb receipt recording suspects that are no longer
present is what success looks like. And never edit a `github` value to make
a count come out better: the signature covers it, and rewriting it forges
somebody's attestation.

---

## Building

### Names

**The tier suffix never reaches a repository name or a domain.** The suffix
records what the fitting looked like at the moment of download, which is a
fact about the file, not the device. The shop itself never reads a tier from
a filename, because a name that could promote a file by being edited would
defeat the point of signed per-row claims. Here the reason is different and
just as firm: a repository name, a domain, a config entry and a device
registry entry are all permanent, and baking a transient label into them
means somebody's install carries it forever.

**The `<kind>` is HAIR's word, not the file's.** HAIR 0.16 turned kind into
a fixed list of twenty-six words plus `other`, and it reads a few known
spellings as list words at display time without rewriting any file:
`airconditioner` reads as `ac`. A name is permanent; a spelling in
somebody's file is not. (Adopted 2026-09-22. The publish tool still names
from the filename stem and does not apply it yet, which is why the runbook
makes a mismatch a stop.)

**Per device, not per brand.** `<brand>_ir` collides the day that brand
sells a second product.

**The wig carries its own future name.** The wig file in the Wig Shop is
`<brand>-<kind>-<model>.wig.json`, so the repository name is the wig's stem
plus `-ir`. That is deliberate. A wig carries its own future name from the
day it lands.

**The `-ir` suffix names the medium, and it goes in the domain too.** Radio
frequency is the obvious second medium, and `-rf` is the obvious second
suffix. A repository suffix alone would not be enough: two repositories can
have different names and still ship components with the same domain, and
Home Assistant cannot load two integrations that share one. So an IR and an
RF version of one device need `sanmli_th05_ir` and `sanmli_th05_rf`, not one
`sanmli_th05` fought over.

**Why the domain is permanent.** The domain is close to invisible to users.
It is the folder under `custom_components/`, the string in `manifest.json`,
`DOMAIN` in `const.py`, and the prefix on log lines. It does not reach
entity IDs, because entities are named from the device. But it is baked into
the config entry and the device registry the moment somebody installs, so
changing it later is not a rename: their integration goes unavailable, they
re-add it, and they lose their entity IDs and history.

**Casing.** Home Assistant requires lowercase of the domain and enforces it
in hassfest, the Wig Shop enforces it on the wig filename with a regex, and
GitHub lowercases repository topics itself. Casing is not a discoverability
lever either: GitHub search is case insensitive, so what surfaces a
repository is the description, the topics and the README body, not the shape
of the slug.

**Identity fields feed labels, never identifiers,** for three reasons.

- They are mutable. Nothing about a claim covers them: a row digest is
  `pronto`, `ditto_count` and `bypass_protocol`, so brand and model can be
  corrected without invalidating a single claim. The filename cannot drift,
  because under the shop's immutability rule a rename is a new file.
- They are free text. `name` on the candle wig is `Candles (Tea Light)`, and
  parentheses are not legal in a repository name. Deriving identifiers from
  them means a sanitizer, which is a hand-applied casing spec hiding in
  code.
- `model` is `TH-05`. Field-derived naming reintroduces the inner dash that
  the squashing rule exists to remove, and then nothing can tell a segment
  separator from part of a model number.

### Codebook integrations

**Press state is excluded** from the codebook because the RC-5 toggle bit is
frozen at capture time and means nothing about which button was pressed.

**Why the gate comes first.** It is the gate, and a gate you write after the
thing it guards is a gate you wrote to pass.

**Reverse decoding** is the direction that proves the integration can hear
the physical remote correctly, and it is only possible because the decoder
is a separate implementation from the encoder.

**Coverage both ways,** because a generated integration that quietly dropped
three buttons passes every other check.

**The send count check is not about the codec at all:** a codec can be
perfectly right and the integration still look broken, because the frames
never arrived. Above the wig's number is allowed, since more frames cost
airtime and not correctness.

**`assumed_state`.** IR is fire and forget, so assumed state is not a
shortcut, it is the truth.

**Optional receivers.** Receivers are optional everywhere in this ecosystem
and this is not the place to change that.

**Dual timing shapes in `event.py`.** That dual shape tolerance is what let
HAIR skate through the migration that broke `lg_infrared`.

**Frames per press comes from the wig.** Real remotes do not send one frame.
RC-5 re-sends the same code every 114ms for as long as the key is held, so a
physical press is three or four frames, and a battery powered device that
duty cycles its receiver can sleep straight through a single frame. The
symptom is a button that works on the first press sometimes and needs three
other times, with no pattern, on a codebook that is completely correct. The
codec checks cannot see it, because encoding and decoding are both fine. The
gate refuses a default below the wig's number because shipping under it
reproduces a fault somebody already found and wrote down. A press is one
press, so the toggle advances once per press: advancing per frame tells the
device it was pressed three times, which is exactly what toggle exists to
distinguish. A send count is about a room, and the next person's room is not
this one, which is why it is the one recipe field left out of the row
digest.

**No VCS URLs in requirements.** hassfest and HACS both pass it and the
config flow then fails with a 500 at runtime, which is a miserable
afternoon.

### Climate integrations

The rulings behind the shape are in
[`plans/climate-build-path.md`](plans/climate-build-path.md).

**The 50 ms terminator** (GH #98). Broadlink RM4 Pro firmware garbles a
stream that ends on a mark, and the 200 ms capture silence at the end of
every Pronto overflows a 16-bit emitter. Upstream's `ProntoCommand` only
exists from infrared-protocols 8.x, which is why the integration carries its
own conversion.

**No Home Assistant imports in `lattice.py` and `command.py`.** That is what
lets the gate import them.

**Restoring from stored data.** Home Assistant converts attributes to the
installation's unit system, so on an imperial install a saved target of 86
reads back as 86 degrees Celsius. Found on the test box, which runs
imperial.

### The README

A confidently wrong manufacturer is worse than an honest unknown, and much
worse if the codec ever goes upstream carrying it.

The shop commit is what lets a reader reproduce the fitting evidence exactly
as the factory saw it, rather than having to trust that the count was right
on the day.

Frames per press is the single most likely thing to need adjusting on
hardware other than the bench set. A reader who knows the number came from
somebody's bench will reach for the setting instead of filing a bug.

The ditto count gets stated because somebody who finds the send-count
setting will otherwise assume it is the only repeat in play.

---

## Publishing

### Why the publish path is automated

Ground rule 8 and the owner's standing instruction are that you hand over
git commands rather than running them. The publish path is the exception,
and only the publish path. The reason is volume: this is meant to run over
many wigs, and a human pasting repository creation commands per device is
the bottleneck the factory exists to remove.

**The tool re-runs the gate itself.** This is load bearing: a green run from
earlier proves nothing about the tree now, so publication is gated by
construction rather than by whoever remembered.

**Create only.** Once published, an integration has its own life: somebody
opens a pull request, it gets merged, and the repository now holds commits
the factory has never seen. A publisher that re-pushed would destroy them
silently.

**Dry run by default.** A bad run leaves a public repository carrying the
organization's name, and unlike a bad commit you cannot quietly amend it
away.

### Repository settings that do not live in a file

**Topics.** The HACS action checks that the topic list is not empty and
nothing more. It does not require any particular topic, and the widely
repeated claim that `home-assistant` and `hacs-integration` are mandatory is
false: both sit on HACS's own `TOPIC_FILTER` denylist, which strips them
because every HACS repository carries them and they are worthless for
search.

**Description and Issues.** Both are checked by the action, neither lives in
a file, and both are easy to forget because they are set on the repository
rather than committed to it.

**`hacs.json`.** HACS's schema uses `PREVENT_EXTRA`, so an unknown key is a
hard validation failure rather than something ignored. `render_readme` is
accepted but vestigial, with no consumers in current HACS.

**The brand icon.** The action's brand check wants it, and since Home
Assistant 2026.3 an integration can ship its own brand images rather than
registering in `home-assistant/brands`. Note the gap: HACS's own panel still
reads `brands.home-assistant.io` for update entity icons, so a locally
shipped icon renders everywhere in Home Assistant except inside HACS itself.
Living with a placeholder there is fine; the brands repository submission is
optional and separate.

### Why the release matters, and it is not ceremony

With no releases at all, HACS installs from the default branch and treats
the branch HEAD as the version, showing users a seven character commit SHA.
Every commit that lands then reads as an available update, including a
README typo and every merged pull request, and there are no release notes to
explain any of it. That is how people learn to ignore your updates.

The moment one release exists, HACS stops looking at the branch entirely:
its version selection checks for a release first and only falls through to
the branch when there is none. So cutting `v0.1.0` at creation is what makes
main safe to commit to. It also keeps the door open to the HACS default
store later, which hard-requires a published release and does not accept a
bare tag.

### Credentials

Using `gh` when it is present keeps the credential in the OS keychain, so
nothing here ever handles a secret. Naming where a secret lives is a leak
even when the secret is not in the file.

---

## Maintaining

### Updates are automated because they are common

More people claim a wig; the shop publishes a successor with a new `wig_id`
at the same filename; the send count moves; the stamp goes stale. That
happens far more often than a first publish.

**`--merge` waits for the checks first** and refuses to merge on a failure,
or on not being able to tell. That is not politeness. The first automated
update merged its own pull request about twenty seconds into a forty-nine
second validation run, and deleting the branch mid-run made the HACS
action's lookup of the head ref return Not Found. The visible symptom was a
red cross on a run that no longer mattered; the real problem was that the
merge had not waited for anything and would have gone through had the run
been genuinely failing.

**It never pushes to the default branch,** because a published integration
accrues commits the factory never saw and that is where the collision
becomes visible. **It never deletes,** because somebody adding a
CONTRIBUTING should not lose it to a stamp refresh. **It refuses a change
without a version bump,** because Home Assistant shows the manifest version
to users and HACS tracks the release tag, so a change that moves neither
means somebody's install quietly stops matching what it says it is.

### Upstream, and the line the factory does not cross

Upstream asks that a library contribution links a core pull request, even a
draft, so the library stays tied to real usage.

`reference/infrared-protocols/AI_POLICY.md` constrains this project
specifically. The Open Home Foundation policy says, in its own words:

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

The gate proves the codec matches the captured signals. It does not transfer
anybody's understanding, and understanding is what upstream is asking for.

### The shared codec package, decided but not yet built

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
