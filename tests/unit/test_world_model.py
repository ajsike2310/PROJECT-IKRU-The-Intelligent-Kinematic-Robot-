"""TC10-TC12: world-model helpers. Technique: Equivalence Partitioning / Boundary Value Analysis."""
import pytest


@pytest.mark.parametrize("seconds, expected", [
    (0, "just now"),
    (44, "just now"),                  # boundary: last second of "just now"
    (45, "about a minute ago"),        # boundary: first second of the next class
    (600, "about 10 minutes ago"),
    (7200, "about 2 hours ago"),
    (172800, "about 2 days ago"),
])
def test_tc10_ago_phrase_boundaries(world_model, seconds, expected):
    assert world_model.ago_phrase(seconds) == expected


@pytest.mark.parametrize("angle, expected", [
    (0, "straight ahead"),
    (25, "straight ahead"),            # boundary
    (26, "to your left"),
    (-60, "to your right"),
    (150, "behind you"),               # boundary
])
def test_tc11_describe_direction(world_model, angle, expected):
    assert world_model.describe_direction(angle) == expected


def test_tc12_labels_match_and_clean_label(world_model):
    assert world_model.labels_match("coffee mug", "white mug")
    assert not world_model.labels_match("coffee mug", "tennis ball")
    assert world_model.clean_label("  The   Red Cup ") == "red cup"


def test_pose_updates_with_dead_reckoning(world_model):
    wm = world_model.WorldModel()
    wm.apply_forward(30)
    assert wm.x == pytest.approx(30.0)
    wm.apply_turn(90)
    wm.apply_forward(20)
    assert (round(wm.x), round(wm.y)) == (30, 20)
    assert wm.distance_travelled_cm == pytest.approx(50.0)
    wm.apply_turn(200)                 # wraps into (-180, 180]
    assert -180 < wm.heading <= 180
