# wigs/

Drop the `.wig.json` you are building from in here.

Wigs come from the [Wig Shop](https://github.com/DAB-LABS/WigShop). Take the
current file from the repository rather than an older copy. Two things move
under a filename that does not: the shop accumulates claims from new people,
and a corrected wig is published as a successor carrying a new `wig_id` at
the same name. An old copy can therefore be the wrong codes, not just fewer
signatures.

A shop file that carries a Perfect Fit is named
`<brand>-<kind>-<model>-perfect-fit.wig.json`. Since 2026-09-16 the shop also
keeps wigs with no fitting, named without the suffix, and this factory refuses
to build from those. The suffix describes the file rather than the device and
is stripped everywhere it would become permanent, so the repository is
`<brand>-<kind>-<model>-ir`.

Nothing in this folder is authoritative. It is a scratch input directory, and
the shop is the record.
