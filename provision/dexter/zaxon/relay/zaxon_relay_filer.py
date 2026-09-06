"""Files a GitHub issue pointer when an inbox note gets tagged for a repo.

crt#154 (Zach, 2026-09-06, decision on the issue): a tagged voice note
becomes a real issue in its target repo without waiting for that repo's own
nightly agent to poll fetch_inbox. **The issue is a pointer, never a
paste** -- title and body carry only the inbox row's id and metadata, never
its message. The transcript stays in the inbox; the target repo's own agent
reads it with fetch_inbox, using the id this issue names. That split is what
makes auto-filing safe into a repo that may be public, or an unreviewed
voice note that may name something it shouldn't have.

Retagging a note that was already filed closes the stale pointer (with a
comment saying why) and files a fresh one in the new repo, rather than
leaving an issue open in a repo the note no longer addresses.
"""
import logging
import os
import subprocess

from zaxon_relay_db import get_conn

logger = logging.getLogger("zaxon_relay_filer")

GH_OWNER = os.environ.get("ZAXON_FILER_GH_OWNER", "hf7y")


def _repo_nwo(repo: str) -> str:
    return repo if "/" in repo else f"{GH_OWNER}/{repo}"


def _run_gh(args: list) -> str:
    # The one subprocess boundary in this module -- tests stub this out and
    # never shell out to a real `gh`.
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=30, check=True
    )
    return result.stdout.strip()


def _title(entry_id: str, via: str, received_at: str) -> str:
    # Never the transcript, and never derived from it -- crt#154's title
    # rule. Tag + timestamp only.
    return f"Voice note tagged for this repo: inbox {entry_id} ({received_at}, via {via})"


def _body(entry_id: str, reply_to_id) -> str:
    lines = [
        "A note in the Zaxon inbox was tagged for this repo.",
        "",
        f"- inbox id: `{entry_id}`",
        f"- reply_to_id: `{reply_to_id}`" if reply_to_id else "- reply_to_id: none",
        "",
        "The transcript stays in the inbox, not here. Fetch it with "
        "`fetch_inbox` (the Zaxon relay MCP tool) using the id above -- "
        "do not paste the transcript into this issue.",
    ]
    return "\n".join(lines)


def create_pointer_issue(
    entry_id: str, repo: str, via: str, received_at: str, reply_to_id=None
) -> str:
    """Files the pointer issue and returns 'owner/repo#N'."""
    nwo = _repo_nwo(repo)
    out = _run_gh(
        [
            "issue",
            "create",
            "--repo",
            nwo,
            "--title",
            _title(entry_id, via, received_at),
            "--body",
            _body(entry_id, reply_to_id),
        ]
    )
    # `gh issue create` prints the created issue's URL as its last line.
    url = out.splitlines()[-1].strip() if out else ""
    number = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
    return f"{nwo}#{number}" if number else nwo


def close_pointer_issue(filed_ref: str, comment: str) -> None:
    """filed_ref is 'owner/repo#N'. Closes with a comment rather than
    deleting -- a closed issue with a note is the honest trail."""
    repo, _, number = filed_ref.rpartition("#")
    if not repo or not number:
        return
    _run_gh(["issue", "close", number, "--repo", repo, "--comment", comment])


def file_if_tagged(entry_id: str, conn=None) -> str:
    """Call after a row's for_agent is set (spoken tag or retag). Returns the
    filed 'owner/repo#N' ref, or None if the row is unknown or untagged.

    Idempotent: a row already filed for the SAME repo is left alone. A row
    retagged to a DIFFERENT repo closes the old pointer and files a new one
    (crt#154's retag-moves-the-issue requirement)."""
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT for_agent, filed_issue, via, received_at, reply_to_id "
            "FROM inbox WHERE id=?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        for_agent, filed_issue, via, received_at, reply_to_id = row
        if for_agent is None:
            return None
        target_nwo = _repo_nwo(for_agent)
        if filed_issue:
            filed_repo = filed_issue.split("#", 1)[0]
            if filed_repo == target_nwo:
                return filed_issue  # already filed where it belongs
            close_pointer_issue(
                filed_issue,
                f"Retagged to {for_agent} -- inbox {entry_id} is now filed there instead.",
            )
        new_ref = create_pointer_issue(entry_id, for_agent, via, received_at, reply_to_id)
        conn.execute("UPDATE inbox SET filed_issue=? WHERE id=?", (new_ref, entry_id))
        conn.commit()
        logger.warning(
            "filed pointer issue %s for inbox %s (for_agent=%s)", new_ref, entry_id, for_agent
        )
        return new_ref
    finally:
        if owns_conn:
            conn.close()
