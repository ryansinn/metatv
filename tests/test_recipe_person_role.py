"""A person ingredient defaults to Any role; its toggle cycles Acting → Directing."""
from types import SimpleNamespace

from PyQt6.QtWidgets import QPushButton

from metatv.gui.recipe_bar_widgets import _IngredientFlow
from metatv.gui.recipe_view import RecipeView


def test_the_role_toggle_moves_the_person_between_facets_and_keeps_state():
    calls = []
    host = SimpleNamespace(
        _recipe_includes={"person": {"Clint Eastwood"}},
        _recipe_excludes={"cast": {"Bob"}},
        _recipe_bar=SimpleNamespace(update_recipe=lambda *a: calls.append(a)),
        _results_debounce=SimpleNamespace(start=lambda: calls.append("load")),
    )
    RecipeView._on_ingredient_role(host, "person", "Clint Eastwood")
    assert host._recipe_includes == {"cast": {"Clint Eastwood"}}
    RecipeView._on_ingredient_role(host, "cast", "Clint Eastwood")
    assert host._recipe_includes == {"director": {"Clint Eastwood"}}
    RecipeView._on_ingredient_role(host, "director", "Clint Eastwood")
    assert host._recipe_includes == {"person": {"Clint Eastwood"}}, "wraps back to Any"
    RecipeView._on_ingredient_role(host, "cast", "Bob")
    assert host._recipe_excludes == {"director": {"Bob"}}, "an exclusion stays an exclusion"
    assert "load" in calls


def test_a_person_pill_carries_its_role_button(qapp, owned_widgets):
    flow = owned_widgets.own(_IngredientFlow())
    got = []
    flow.role_clicked.connect(lambda f, v: got.append((f, v)))
    flow.set_ingredients([("person", "Clint Eastwood", False), ("genre", "Drama", False)])
    roles = [b for b in flow.findChildren(QPushButton) if b.text() == "Any"]
    assert len(roles) == 1, "only the person gets a role toggle"
    roles[0].click()
    assert got == [("person", "Clint Eastwood")]
