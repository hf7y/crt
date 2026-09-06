"""Files a pointer issue in an inbox entry's target repo once it is tagged.

crt#154, decided by Zach 2026-09-06: auto-file, but the issue never carries
the transcript -- it points at the inbox row. A misheard note that files a
pointer costs one close; one pasted verbatim into a public repo cannot be
unpublished, and not every target repo is even public. `gh`'s own default
issue view (`gh issue view <url>`) is how a repo's agent confirms the tag;
`fetch_inbox`/`get_entry` with the id in the body is how it reads the note.
"""
import logging
import subprocess

logger = logging.getLogger("zaxon_relay_filer")

ORG = "hf7y"


def _default_creator(repo: str, title: str, body: str) -> str:
    proc = subprocess.run(
        ["gh", "issue", "create", "--repo", f"{ORG}/{repo}", "--title", title,
         "--body", body],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return proc.stdout.strip().splitlines()[-1]  # `gh issue create` prints the URL last


def _default_closer(issue_url: str, comment: str) -> None:
    subprocess.run(
        ["gh", "issue", "close", issue_url, "--comment", comment],
        capture_output=True, text=True, timeout=30, check=True,
    )


def repo_from_issue_url(issue_url: str) -> str:  # https://github.com/<org>/<repo>/issues/<n> -> <repo>
    return issue_url.rstrip("/").split("/")[-3]


def issue_title(entry_id: str, received_at: str) -> str:
    # Never the transcript's first line -- crt#154's own ruling forbids it.
    return f"Voice note tagged for this repo: inbox {entry_id} ({received_at})"


def issue_body(entry_id: str, via: str, received_at: str) -> str:
    return (
        f"A {via} note tagged for this repo arrived {received_at}.\n\n"
        "The transcript stays in the inbox, not here -- this issue is a "
        f"pointer, not a paste (crt#154). Read it with `fetch_inbox` or "
        f"`get_entry(\"{entry_id}\")`, inbox id `{entry_id}`.\n"
    )


def file_entry(entry_id: str, repo: str, via: str, received_at: str, creator=None) -> str:
    """Files the pointer issue for a freshly-tagged entry and returns its URL."""
    create = creator or _default_creator
    return create(repo, issue_title(entry_id, received_at), issue_body(entry_id, via, received_at))


def refile_entry(entry_id: str, old_issue_url, new_repo: str, via: str, received_at: str,
                  creator=None, closer=None) -> str:
    """A retag moves the pointer (crt#154: 'retag should move or close the
    filed issue, not just relabel the inbox row'). Files fresh under
    `new_repo` first, then closes whatever was filed under the old one --
    so a closer that raises never leaves the entry unfiled."""
    new_url = file_entry(entry_id, new_repo, via, received_at, creator=creator)
    if old_issue_url:
        close = closer or _default_closer
        try:
            close(old_issue_url, f"retagged to {new_repo}: {new_url}")
        except Exception:  # noqa: BLE001 -- the new issue is already filed; a stray old one stays open, not unfiled
            logger.warning("could not close superseded issue %s for entry %s", old_issue_url, entry_id)
    return new_url
