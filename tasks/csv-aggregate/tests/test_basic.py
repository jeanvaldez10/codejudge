from solution import aggregate


def test_simple_group_by():
    text = "team,points\nred,3\nblue,5\nred,4\n"
    assert aggregate(text, "team", "points") == {"red": 7.0, "blue": 5.0}
