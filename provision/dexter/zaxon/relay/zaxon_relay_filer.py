"""Files a pointer issue in a tagged note's target repo -- never the
transcript itself (crt#154, Zach 2026-09-06 via realisateur /ideate):
"file it, but don't reveal content in the issue, just point to the file."

A misheard note that files a pointer costs one close. A misheard note
pasted verbatim into a public repo cannot be unpublished -- crt is public
(crt#148) and every commit is exposed, not just the tip.

Inbox rows are retained forever: nothing in this relay deletes or expires
an inbox row (checked 2026-09-06 -- only ticket CLAIMS have a TTL, in
zaxon_relay_inbox.CLAIM_TTL_SECS). So a filed issue's pointer id always
resolves; there is no rotation window to race.

Filing goes through `defere`, not a hand-built `gh issue create`: this
estate's `gh` is gh-sign, which refuses any agent-written issue/close body
that does not satisfy realisateur's lib/body-grammar.sh (a DECISION/
NO-DECISION line, a DEFERRED ledger, a DELIVERS ledger). `defere --project
<repo>` already produces a compliant NO-DECISION body ("routed and owned
there; nothing here needs a call") -- reimplementing that grammar here
would only drift from it.
"""
import re
import subprocess

DEFERE_BIN = "defere"

_ISSUE_URL_RE = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/issues/(\d+)")


def issue_title(repo: str, tagged_at: str) -> str:
    """Never the transcript, even truncated -- that's the shortcut the
    ruling explicitly forbids, in the most visible field there is."""
    return f"voice note tagged {repo} ({tagged_at})"


def issue_body(entry_id: str, repo: str, tagged_at: str) -> str:
    return (
        f"A voice note in the Zaxon relay inbox was tagged for `{repo}`.\n\n"
        f"- inbox id: `{entry_id}`\n"
        f"- tagged: {tagged_at}\n\n"
        "The transcript is not reproduced here (crt#154) -- read it with "
        "`fetch_inbox`/`claim_inbox_entry` using the id above. If the id "
        "does not resolve, say so on this issue rather than guessing at "
        "what it might have said."
    )


def _default_creator(repo: str, title: str, body: str) -> str:
    """Returns 'owner/repo#N'. Raises on failure -- a caller must never
    record a filed_issue that was not actually created."""
    proc = subprocess.run(
        [DEFERE_BIN, title, "--project", repo, "--body", body],
        capture_output=True, text=True, timeout=30, check=True,
    )
    m = _ISSUE_URL_RE.search(proc.stdout)
    if not m:
        raise RuntimeError(f"defere reported success but gave no issue URL to parse: {proc.stdout!r}")
    return f"{m.group(1)}#{m.group(2)}"


def _default_closer(issue_ref: str, comment: str) -> None:
    owner_repo, number = issue_ref.rsplit("#", 1)
    subprocess.run(
        ["gh", "issue", "close", number, "--repo", owner_repo, "--comment", comment],
        capture_output=True, text=True, timeout=30, check=True,
    )


def file_issue(entry_id: str, repo: str, tagged_at: str, creator=None) -> str:
    """Returns the filed issue ref ('owner/repo#N'). `creator` is
    injectable for tests."""
    create = creator or _default_creator
    return create(repo, issue_title(repo, tagged_at), issue_body(entry_id, repo, tagged_at))


def close_for_retag(old_issue_ref: str, new_issue_ref: str, closer=None) -> None:
    """The note moved to a different repo -- the old pointer now names the
    wrong target, so close it rather than leave a stale one nobody reads.
    The comment must name `new_issue_ref` itself, not just a repo: gh-sign's
    close_check refuses a close whose comment names nothing a check could go
    and look at, and a bare repo name is not that. `closer` is injectable
    for tests."""
    close = closer or _default_closer
    close(old_issue_ref, f"Retagged -- see {new_issue_ref}. (crt#154)")
