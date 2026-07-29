# Security

The [Wig Shop](https://github.com/DAB-LABS/WigShop) holds data. This
repository produces **code that people install into Home Assistant**, and
that difference is the whole reason the bar here is higher.

A wrong wig transmits a wrong code. A wrong integration is a Python package
running inside somebody's Home Assistant, published under this
organization's name, installed through HACS by people who trusted the name
rather than reading the source. The threat model is real here in a way it is
not one repository upstream.

## What the gate is for

`verify/verify_wig.py` is not a linter and it is not a formality. It exists
because an LLM writing an IR codec will sometimes write a plausible, well
structured, entirely wrong one, and nothing about reading the code will tell
you which kind you got.

The gate checks the generated codec against HAIR's own protocol decoders,
which never saw it. Forward, so the generated encoder produces what the wig
says. Reverse, so a vendored decoder reads what the wig contains. Coverage,
so nothing was silently dropped or invented.

**Publishing generated code that has not passed the gate in both directions
is the security failure this project is most likely to actually have.** Not
a token leak, not a supply chain attack. That.

If you see a published integration whose README does not carry a content
hash, a fitting record and a statement that the gate passed, treat it as
unverified and say so in an issue.

## What to report, and how

**A published integration that misbehaves.** Open a normal issue, here or on
the integration's own repository. Say which device, which entity, and what it
actually did. Wrong IR output is annoying rather than dangerous, but it is
exactly the failure the gate is supposed to prevent, so a report tells us the
gate has a hole.

**A way to defeat the gate.** If you can construct a wig or a generated
codebook that passes `verify_wig.py` while being wrong, that is the most
valuable bug report this project can receive, and it is not a public issue.
Email **david.a.bailey@gmail.com** with a reproduction. You should get an
acknowledgment within a couple of days.

**Anything that executes.** The workflow tells an agent to clone
repositories, run scripts and generate files. If you find a path where a wig
file, a repository name or a reference clone can cause code execution during
a build, or can get something into a published artifact that nobody wrote,
email rather than posting it.

**A dishonest fitting chain.** Fittings from three handles that are really
one person defeat the promotion bar. CI in the Wig Shop flags shared signing
keys, which catches the lazy version of this and not the careful version.
Report suspicions to the email above rather than in public, because the
accusation is about a person.

## What signatures prove, and what they do not

A fitting can carry an ed25519 signature made with a key generated on the
fitter's own HAIR install.

It proves the record has not been altered since it was made on that install,
and that fittings sharing a key came from one install. It does not prove who
the fitter is. Nobody verified the handle, and the GitHub name is checkable
only by asking that person.

That is tamper evidence on a social claim, and the documentation here should
never describe it as more than that.

## License hygiene is a security property here

Generated codecs are written from protocol specifications. No code derived
from GPL or LGPL implementations goes into them, because these files are
meant to graduate into Apache-2.0 licensed upstream `infrared-protocols`,
and a contaminated file discovered after that donation is a problem for
somebody else's project as well as this one.

If you recognize code in a generated codec as lifted from another
implementation, that is worth an email.

## Reporting HAIR itself

Anything about the integration rather than the factory belongs on
[HAIR's security policy](https://github.com/DAB-LABS/HAIR/blob/main/SECURITY.md).
