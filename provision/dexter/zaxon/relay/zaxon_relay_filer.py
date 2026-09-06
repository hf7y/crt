"""Files a pointer issue, never the transcript, for a tagged inbox entry
(crt#154). Goes through `defere --project`, not `gh issue create` directly:
this estate's `gh` is gh-sign and refuses a body that fails body-grammar.
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


def _title(repo: str, entry_id: str, received_at: str) -> str:  # never the transcript's first line
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


def _default_creator(repo: str, title: str, body: str) -> str:  # -> 'owner/repo#N'; raises on failure
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


def _default_closer(issue_ref: str, comment: str) -> None:  # issue_ref is 'owner/repo#N'
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


def file_issue(entry_id: str, conn=None, creator=None, closer=None) -> str:  # -> 'owner/repo#N' or None; a None leaves filed_issue as it was, so a later retry can still succeed
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
            except _FILING_ERRORS as e:  # new issue is already recorded; a stray old one stays open
                logger.warning("could not close superseded issue %s for entry %s: %s", filed_issue, entry_id, e)

        return new_ref
    finally:
        if owns_conn:
            conn.close()


def file_pending(conn=None, creator=None, closer=None) -> list:  # retries anything file_issue() missed; returns the ids filed
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
