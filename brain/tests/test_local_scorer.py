from brain.local_scorer import priority_for


def test_news2_priority_mapping():
    assert priority_for(4) is None
    assert priority_for(5) == "medium"
    assert priority_for(6) == "medium"
    assert priority_for(7) == "high"


def test_single_parameter_warning_gets_medium_priority():
    assert priority_for(3, "warning") == "medium"
