from solution import topological_sort


def test_lexicographic_tie_break():
    graph = {"d": [], "c": [], "b": ["d"], "a": ["c"]}
    assert topological_sort(graph) == ["c", "a", "d", "b"]


def test_dependency_only_nodes_included():
    assert topological_sort({"x": ["y", "z"]}) == ["y", "z", "x"]


def test_respects_all_edges_on_random_dag():
    import random

    rng = random.Random(5)
    names = [f"n{i:03d}" for i in range(300)]
    graph = {names[i]: rng.sample(names[:i], k=min(i, 4)) for i in range(300)}
    order = topological_sort(graph)
    pos = {n: i for i, n in enumerate(order)}
    assert sorted(order) == sorted(names)
    assert all(pos[d] < pos[n] for n, deps in graph.items() for d in deps)


def test_accepts_tuples_and_sets():
    assert topological_sort({"b": ("a",), "c": {"a", "b"}}) == ["a", "b", "c"]
