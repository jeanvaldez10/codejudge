from solution import LRUCache


def test_update_existing_moves_to_front():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)
    c.put("c", 3)
    assert c.get("a") == 10 and c.get("b") is None


def test_len_tracks_size():
    c = LRUCache(3)
    for i in range(10):
        c.put(i, i)
    assert len(c) == 3
    assert [k for k in range(10) if k in c] == [7, 8, 9]


def test_get_default():
    c = LRUCache(1)
    assert c.get("x", 42) == 42


def test_long_sequence_matches_model():
    import random
    from collections import OrderedDict

    rng = random.Random(1)
    c, model = LRUCache(16), OrderedDict()
    for _ in range(5_000):
        k = rng.randrange(40)
        if rng.random() < 0.5:
            c.put(k, k * 2)
            model[k] = k * 2
            model.move_to_end(k)
            if len(model) > 16:
                model.popitem(last=False)
        else:
            expected = model.get(k)
            if k in model:
                model.move_to_end(k)
            assert c.get(k) == expected
    assert len(c) == len(model)
