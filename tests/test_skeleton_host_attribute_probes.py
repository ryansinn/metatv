"""``hasattr(self, "x")`` in the MainWindow family — a shrink-only budget.

THE TRAP
--------
On a skeleton host — ``MainWindow.__new__(MainWindow)``, the idiom 36 test
files use to drive one method without booting the window — attribute access
goes through Qt's sip layer and raises ``RuntimeError``:

    RuntimeError: '__init__' method of object's base class never called

``hasattr`` does not absorb that (it only swallows ``AttributeError``), and
neither does ``getattr(self, "x", None)`` — the default is never reached,
because the lookup itself raises. So a guard written to mean "skip this widget
if it does not exist yet" EXPLODES instead, and it explodes only in tests,
which is why production has never noticed.

The safe form is used correctly elsewhere in these same files::

    "discover_view" in self.__dict__          # False, no exception

CLAUDE.md documents this and CRITICAL_RULES.md says outright: "never add a
``hasattr(self, "manager_name")`` block."

WHY A BUDGET RATHER THAN A SWEEP
--------------------------------
There are 138 of these. They are latent — no user-visible bug today — and a
mechanical rewrite is not safe to do unverified: ``self.__dict__.get(x)`` and
``getattr(self, x, d)`` differ for class attributes, properties and anything
inherited, so a blind substitution can silently change what a branch reads.

Two test files have already hand-rolled a local ``SimpleNamespace`` workaround
rather than fix production (``test_provider_view_refresh``,
``test_theme_live_refresh``), which is the cost being paid today.

So this is the same shape as the theme layer's ``COMPOSED_BUDGET``: the
population is frozen and may only shrink. New code cannot add one; the existing
ones get paid down deliberately, in a slice with the tests to prove each
conversion. Lower the number when you do.
"""

import ast
import pathlib

#: Frozen population, 2026-08-31. SHRINK ONLY — never raise this to make a
#: new call site pass. Use ``"name" in self.__dict__`` instead.
SKELETON_PROBE_BUDGET = 135


def _probe_sites() -> list[tuple[str, int, str, str]]:
    """Every ``hasattr(self, "literal")`` / ``getattr(self, "literal", …)``.

    AST rather than a regex: the argument may be written across lines, and the
    shape that matters is "first argument is ``self``, second is a string
    literal" — which no line-oriented pattern can see reliably.
    """
    root = pathlib.Path(__file__).resolve().parent.parent / "metatv" / "gui"
    found = []
    for path in sorted(root.glob("main_window*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"hasattr", "getattr"}):
                continue
            if len(node.args) < 2:
                continue
            first, second = node.args[0], node.args[1]
            if (isinstance(first, ast.Name) and first.id == "self"
                    and isinstance(second, ast.Constant)
                    and isinstance(second.value, str)):
                found.append((path.name, node.lineno, node.func.id, second.value))
    return found


def test_the_population_only_shrinks():
    sites = _probe_sites()
    assert len(sites) <= SKELETON_PROBE_BUDGET, (
        f"{len(sites)} self-attribute probes, budget {SKELETON_PROBE_BUDGET}. "
        f"On a skeleton host these raise RuntimeError rather than returning a "
        f"default. Use '\"name\" in self.__dict__'. New sites: "
        f"{sites[-5:]}"
    )


def test_lower_the_budget_when_you_pay_some_down():
    """Keeps the number honest in the other direction.

    A budget nobody lowers is just a permanent exemption. If the population has
    shrunk, this fails and asks for the constant to be updated — the same
    ratchet discipline the code-health baseline uses.
    """
    sites = _probe_sites()
    assert len(sites) == SKELETON_PROBE_BUDGET, (
        f"only {len(sites)} probes remain (budget {SKELETON_PROBE_BUDGET}) — "
        f"lower SKELETON_PROBE_BUDGET to {len(sites)} to lock in the progress")


def test_the_safe_form_is_the_one_in_use_nearby():
    """The alternative is not theoretical — it is already used in these files."""
    root = pathlib.Path(__file__).resolve().parent.parent / "metatv" / "gui"
    src = (root / "main_window_nav.py").read_text()
    assert "in self.__dict__" in src, (
        "the safe idiom vanished from main_window_nav.py, which means the "
        "budget above is now the only documentation of it")
