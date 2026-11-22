from solution import aggregate


def test_quoted_commas_in_key():
    text = 'name,amount\n"Smith, J",10\n"Smith, J",2.5\nLee,1\n'
    assert aggregate(text, "name", "amount") == {"Smith, J": 12.5, "Lee": 1.0}


def test_preserves_first_seen_order():
    text = "k,v\nb,1\na,1\nb,1\nc,1\n"
    assert list(aggregate(text, "k", "v")) == ["b", "a", "c"]


def test_column_order_independent():
    text = "v,other,k\n1,x,a\n2,y,a\n"
    assert aggregate(text, "k", "v") == {"a": 3.0}


def test_crlf_line_endings():
    text = "k,v\r\na,1\r\nb,2\r\n"
    assert aggregate(text, "k", "v") == {"a": 1.0, "b": 2.0}
