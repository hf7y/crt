# sonne

*ring the handset: voice front end for a terminal*

This is the **bashified** branch of `crt`. It contains a plain shell
utility and nothing else.

```
bin/sonne          the utility
man/sonne.1        how to use it
CONTRACT.md    the promise it must keep
GAPS.md        what it cannot do yet
test/          the contract test, runnable against any implementation
```

## Why this is a branch and not a repository

The purge here is **total**. Everything this tree used to carry beyond
the tool itself is gone from these files. It is not lost: it is on `main`
branch of this same repository, one `git log main` away.

**That is the only reason a total purge is safe.** Extracting this
branch into a standalone repository would destroy the archive that
justifies the purge, and leave defensive code standing with no visible
cause -- which is how hard-won guards get deleted by the next reader.
Do not do it.

## Verify

```
./test/contract-test.sh bin/sonne
```
