#!/usr/bin/env python3
# One place to resolve a config value that more than one script needs.
#
# WHY THIS FILE EXISTS: vault:crt/REFACTOR-ASSESSMENT.md / ranked-backlog item 1
# ("introduce one config source ... for the port 8993, whisper URL, and
#   [rest: vault:crt/header-archaeology-20260817.md]
import os

BIN_DIR = os.path.dirname(os.path.abspath(__file__))

FIXUPS_DEFAULT = os.path.join(BIN_DIR, "stt-fixups.json")
FIXUPS_ENV = "CRT_STT_FIXUPS"
FIXUPS_ENV_LEGACY = "CRT_STT_FIXUPS_PATH"


# THE THIRD INSTANCE (2026-07-25, twentieth cycle): "what number did the shell
# put in this env var, and what if it isn't one?"
#
# Every tunable in bin/ is read as a bare int()/float() of an env var, and
#   [rest: vault:crt/header-archaeology-20260817.md]
def env_number(name, default, env=None, minimum=0.0):
    """A numeric env var, junk-tolerant. Returns `default` for unset, for
    anything float() refuses, and for anything below `minimum`.

    `minimum` defaults to 0, which accepts zero -- several of these use 0 as
    "disable" (CRT_BOOK_IDLE_ROTATE_SECS, CRT_SCREENSAVER_CAPTION_MOVE_SECS),
    and an automatic behaviour keeping its manual escape hatch is a rule this
    project applies everywhere. Pass a positive minimum where zero is not an
    escape hatch but a hot loop.

    Returns a float. Callers that need an int convert at the point of use --
    nothing here is an index, and every current caller feeds time.sleep or
    arithmetic."""
    raw = (os.environ if env is None else env).get(name)
    if raw is None:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    return val if val >= minimum else default


def env_flag(name, default=False, env=None):
    """An on/off env var, junk-tolerant, for the same reason env_number is.

    '1'/'true'/'yes'/'on' (any case) are on, '0'/'false'/'no'/'off' are off,
    and ANYTHING else -- including the empty string -- is `default`. The
    generous vocabulary is the point: the one flag this was written for
    (CRT_LOOP_GUARD_TRACEBACK) is a debugging switch a person sets by hand
    while chasing a window that keeps dying, and `int()` of the perfectly
    reasonable `CRT_LOOP_GUARD_TRACEBACK=true` raised -- killing all four
    guarded windows at once, from inside the module whose entire job is
    keeping them alive."""
    raw = (os.environ if env is None else env).get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default

# THE SECOND INSTANCE (2026-07-25, nineteenth cycle): "is the tmux pane this
# console types into a Claude brain, or the idle face?"
#
# bin/crt-console.sh hands the stt window CRT_TMUX_PANE=0.0 on ONE line, for
#   [rest: vault:crt/header-archaeology-20260817.md]
PANE_ENV = "CRT_TMUX_PANE"
PANE_DEFAULT = "0"
IDLE_FACE_ENV = "CRT_IDLE_FACE_WINDOW"


def fixups_conflict_report(canonical, legacy):
    """Pure string builder. Names both values, because the whole failure is
    that two halves of the learning loop are pointed at different files and
    each one looks fine from where it stands."""
    return ("[!] %s=%s and %s=%s disagree -- using %s; the other half of "
            "the fixups loop is writing somewhere this will never read"
            % (FIXUPS_ENV, canonical, FIXUPS_ENV_LEGACY, legacy, canonical))


def fixups_path(env=None, warn=None):
    """The one answer to 'where is stt-fixups.json'. Honours both spellings,
    prefers the canonical one, and does not raise: this is called at import
    by crt-stt-solo.py, and a config-shaped complaint must never be the
    reason the STT engine fails to start. A genuine disagreement is
    reported through `warn` (default: print to the caller's own pane)."""
    env = os.environ if env is None else env
    canonical = env.get(FIXUPS_ENV)
    legacy = env.get(FIXUPS_ENV_LEGACY)
    if canonical and legacy and canonical != legacy:
        (warn or print)(fixups_conflict_report(canonical, legacy))
    return canonical or legacy or FIXUPS_DEFAULT


def pane_window(target):
    """The WINDOW half of a tmux pane target: '0.0' -> '0', '0' -> '0',
    'book.1' -> 'book'. Pure string work on purpose -- this is called at
    import by the sole mic reader, and asking a tmux server to resolve a
    window name would put a subprocess in that path (and answer nothing at
    all when the console is not running, which is how the tests see it)."""
    return str(target or "").split(".", 1)[0].strip()


def pane_is_idle_face(pane=None, env=None):
    """True when the pane this console types into is the IDLE FACE -- a
    screensaver with no brain behind it -- rather than a Claude pane. See
    this file's PANE_ENV block for the two callers and what each one did
    before this existed.

    False whenever CRT_IDLE_FACE_WINDOW is unset or blank: that is the
    historical always-resident-Claude layout, where window 0 really is a
    brain, and nothing about it changes.

    Compares the two values as WRITTEN. crt-console.sh writes both itself
    ('0' and '0.0'), so they match there; a hand-set CRT_IDLE_FACE_WINDOW
    naming the window while CRT_TMUX_PANE gives its index would not, and this
    returns False -- i.e. it degrades to exactly today's behaviour rather
    than suppressing delivery on a guess. Resolving a name against an index
    needs a live tmux server, which is precisely what is missing when this
    matters most."""
    env = os.environ if env is None else env
    idle_face = pane_window(env.get(IDLE_FACE_ENV))
    if not idle_face:
        return False
    pane = env.get(PANE_ENV, PANE_DEFAULT) if pane is None else pane
    return pane_window(pane) == idle_face


def idle_face_pane_report(pane=None, env=None):
    """Pure string builder: why an utterance/keystroke was not delivered.
    Names both halves, because from either side alone the setup looks fine
    -- the pane exists and tmux would accept the keys, which is the whole
    reason this went unnoticed. Short: it lands on a 40-column tube."""
    env = os.environ if env is None else env
    pane = env.get(PANE_ENV, PANE_DEFAULT) if pane is None else pane
    return ("%s=%s is the idle face (%s=%s), not a Claude pane -- "
            "nothing there can act on it"
            % (PANE_ENV, pane, IDLE_FACE_ENV, env.get(IDLE_FACE_ENV, "")))
