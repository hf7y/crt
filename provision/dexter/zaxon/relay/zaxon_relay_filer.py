"""Files a pointer issue in the tagged repo for a tagged inbox entry (crt#154).

Zach's ruling (crt#154, 2026-09-06): "file it, but don't reveal content in
the issue, just point to the file". crt is public and a voice note is
unreviewed speech -- it may name a person, a credential, or an address --
so the transcript never leaves the inbox. The filed issue carries only the
entry id, when it arrived, and how (via); the target repo's next agent
reads the actual words with fetch_inbox(), same call it would have made
under the queue-only design this supersedes.

Filing goes through `defere`, not a hand-built `gh issue create`: this
estate's `gh` is gh-sign (checked on the box this was built on, 2026-09-06 --
`readlink -f /usr/local/bin/gh` resolves to realisateur's build, not a bare
binary), which refuses any agent-written issue body that does not satisfy
realisateur's lib/body-grammar.sh (a DECISION/NO-DECISION line, a DEFERRED
ledger, a DELIVERS ledger). A hand-built `gh issue create --title --body`
would be REFUSED at write time whenever gh-sign is in front of gh -- and
degrades safely to a plain `gh issue create` when it is not, since `defere
--project` is just that call with a compliant body wrapped around it.
`defere --project <repo>` already produces that body ("routed and owned
there; nothing here needs a call") -- reimplementing the grammar here would
only drift from it.

Idempotent by the inbox row itself: a row already filed against the repo it
is currently tagged for is left alone. A retag to a DIFFERENT repo closes
the stale pointer (crt#154: "retag should move or close the filed issue,
not just relabel the inbox row") and files a fresh one, so a mis-tagged
note never leaves an issue open in the wrong repo.
"""
import logging
import re
import subprocess

from zaxon_relay_db import get_conn
from zaxon_relay_queue import validate_repo

logger = logging.getLogger("zaxon_relay_filer")

DEFERE_BIN = "defere"
_ISSUE_URL_RE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/issues/(\d+)")

_FILING_ERRORS = (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, OSError)


def _title(repo: str, entry_id: str, received_at: str) -> str:
    # Title from the tag and the timestamp, NOT the first line of speech --
    # that would reintroduce the exact leak this design forbids, in the
    # most visible field a tracker has.
    return f"Voice note for {repo}: inbox {entry_id} ({received_at})"


def _body(entry_id: str, received_at: str, via: str) -> str:
    return (
        f"A {via} note arrived {received_at} tagged for this repo.\n\n"
        "The words are not in this issue -- crt is public and this repo "
        "may not be, so the transcript stays in the inbox (crt#154). Read "
        f"it with `fetch_inbox`, filtering for entry id `{entry_id}`, then "
        "act on it and close this issue.\n\n"
        f"Wrongly addressed? `tag {entry_id} <repo>` on the relay retags "
        "it and moves this pointer to the new repo automatically."
    )


def _default_creator(repo: str, title: str, body: str) -> str:
    """Returns 'owner/repo#N'. Raises on failure -- a caller must never
    record a filed_issue that was not actually created."""
    proc = subprocess.run(
        [DEFERE_BIN, title, "--project", repo, "--body", body],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    m = _ISSUE_URL_RE.search(proc.stdout)
    if not m:
        raise RuntimeError(f"defere reported success but gave no issue URL to parse: {proc.stdout!r}")
    return f"{m.group(1)}#{m.group(2)}"


def _default_closer(issue_ref: str, comment: str) -> None:
    """issue_ref is 'owner/repo#N'."""
    owner_repo, _, number = issue_ref.rpartition("#")
    subprocess.run(
        ["gh", "issue", "close", number, "--repo", owner_repo, "--comment", comment],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def _filed_for(filed_issue: str) -> str:  # 'hf7y/realisateur#9' -> 'realisateur'
    return filed_issue.split("#", 1)[0].rsplit("/", 1)[-1]


def file_issue(entry_id: str, conn=None, creator=None, closer=None) -> str:
    """Files (or moves) the pointer issue for a tagged entry and records the
    ref against the row. Returns the 'owner/repo#N' ref, or None if there is
    nothing to do (unknown id, untagged, already filed against the current
    tag, bad repo tag) or filing failed -- in every None case the row's
    filed_issue is left as it was, so a later retry (the sweep in
    file_pending, or another retag) can still succeed."""
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT for_agent, received_at, via, filed_issue FROM inbox WHERE id=?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        repo, received_at, via, filed_issue = row
        if repo is None:
            return None
        if filed_issue is not None and _filed_for(filed_issue) == repo:
            return None  # already filed where this entry is currently tagged
        try:
            validate_repo(repo)
        except ValueError as e:
            logger.warning("not filing entry %s: %s", entry_id, e)
            return None

        create = creator or _default_creator
        try:
            new_ref = create(repo, _title(repo, entry_id, received_at), _body(entry_id, received_at, via))
        except _FILING_ERRORS as e:
            logger.warning("filing entry %s against %s failed: %s", entry_id, repo, e)
            return None

        conn.execute("UPDATE inbox SET filed_issue=? WHERE id=?", (new_ref, entry_id))
        conn.commit()
        logger.warning("filed pointer issue %s for inbox %s (for_agent=%s)", new_ref, entry_id, repo)

        if filed_issue is not None:
            close = closer or _default_closer
            try:
                close(filed_issue, f"Retagged to {repo} -- inbox {entry_id} is now filed as {new_ref}.")
            except _FILING_ERRORS as e:
                # The new issue is already recorded; a stray old one stays
                # open rather than the entry going unfiled over this.
                logger.warning("could not close superseded issue %s for entry %s: %s", filed_issue, entry_id, e)

        return new_ref
    finally:
        if owns_conn:
            conn.close()


def file_pending(conn=None, creator=None, closer=None) -> list:
    """Safety net for the tick loop: catches a tagged entry whose immediate
    file_issue() call failed (gh/defere down, transient network) or was
    never reached (retag landed just before a crash). Returns the ids
    filed."""
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM inbox WHERE for_agent IS NOT NULL AND filed_issue IS NULL"
        ).fetchall()
        filed = []
        for (entry_id,) in rows:
            if file_issue(entry_id, conn=conn, creator=creator, closer=closer):
                filed.append(entry_id)
        return filed
    finally:
        if owns_conn:
            conn.close()
