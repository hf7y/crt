"""Files a pointer issue in the tagged repo for a tagged inbox entry (crt#154).

Zach's ruling (crt#154, 2026-09-06): "file it, but don't reveal content in
the issue, just point to the file". crt is public and a voice note is
unreviewed speech -- it may name a person, a credential, or an address --
so the transcript never leaves the inbox. The filed issue carries only the
entry id, when it arrived, and how (via); the target repo's next agent
reads the actual words with fetch_inbox(), same call it would have made
under the queue-only design this supersedes.

Idempotent by the inbox row itself: filed_issue is set exactly once, under
the same atomic "only if still NULL" guard record.py's claim() and assign()
use, so a retry after a crash (this filed but never recorded, watcher
restarted) can at worst file a duplicate issue, never lose the row.
"""
import logging
import subprocess

from zaxon_relay_db import get_conn
from zaxon_relay_queue import validate_repo

logger = logging.getLogger("zaxon_relay_filer")

GH_ORG = "hf7y"


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
        "it -- close this issue rather than acting on it."
    )


def _default_filer(repo: str, title: str, body: str) -> str:
    proc = subprocess.run(
        ["gh", "issue", "create", "-R", f"{GH_ORG}/{repo}", "--title", title, "--body", body],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh issue create failed")
    return proc.stdout.strip()


def file_issue(entry_id: str, conn=None, filer=None) -> str:
    """Files the pointer issue for an already-tagged entry and records its
    URL against the row. Returns the URL, or None if there is nothing to
    file (unknown id, untagged, already filed, bad repo tag) or `gh` failed
    -- in every None case the row is untouched, so a later retry (the sweep
    below, or another retag) can still succeed."""
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
        if repo is None or filed_issue is not None:
            return None
        try:
            validate_repo(repo)
        except ValueError as e:
            logger.warning("not filing entry %s: %s", entry_id, e)
            return None

        do_file = filer or _default_filer
        try:
            url = do_file(repo, _title(repo, entry_id, received_at), _body(entry_id, received_at, via))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            logger.warning("filing entry %s against %s/%s failed: %s", entry_id, GH_ORG, repo, e)
            return None

        cur = conn.execute(
            "UPDATE inbox SET filed_issue=? WHERE id=? AND filed_issue IS NULL",
            (url, entry_id),
        )
        conn.commit()
        return url if cur.rowcount else None
    finally:
        if owns_conn:
            conn.close()


def file_pending(conn=None, filer=None) -> list:
    """Safety net for the tick loop: catches a tagged entry whose immediate
    file_issue() call failed (gh down, transient network) or was never
    reached (retag landed just before a crash). Returns the ids filed."""
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id FROM inbox WHERE for_agent IS NOT NULL AND filed_issue IS NULL"
        ).fetchall()
        filed = []
        for (entry_id,) in rows:
            if file_issue(entry_id, conn=conn, filer=filer):
                filed.append(entry_id)
        return filed
    finally:
        if owns_conn:
            conn.close()
