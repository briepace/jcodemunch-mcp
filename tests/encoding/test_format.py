"""Unit tests for MUNCH format primitives."""

from jcodemunch_mcp.encoding.format import (
    Legends,
    assemble,
    parse_header,
    parse_scalars,
    read_table,
    split_sections,
    write_header,
    write_scalars,
    write_table,
)


def test_header_round_trip():
    h = write_header("get_call_hierarchy", "ch1")
    meta = parse_header(h)
    assert meta == {"tool": "get_call_hierarchy", "enc": "ch1"}


def test_scalars_quoting():
    pairs = {"repo": "foo", "note": "hello world", "n": 42, "flag": True, "none": None}
    line = write_scalars(pairs)
    parsed = parse_scalars(line)
    assert parsed["repo"] == "foo"
    assert parsed["note"] == "hello world"
    assert parsed["n"] == "42"
    assert parsed["flag"] == "T"
    assert parsed["none"] == ""


def test_scalars_embedded_quotes():
    pairs = {"msg": 'she said "hi"'}
    line = write_scalars(pairs)
    parsed = parse_scalars(line)
    assert parsed["msg"] == 'she said "hi"'


def test_table_round_trip():
    rows = [["a.py", 12, "call"], ["b.py", 44, "ref"]]
    text = write_table("c", rows)
    parsed = read_table(text, "c")
    assert parsed == [["a.py", "12", "call"], ["b.py", "44", "ref"]]


def test_legends_dedup_and_encode():
    leg = Legends(prefix="@")
    for v in ["src/foo/", "src/foo/", "src/foo/", "src/bar/", "x"]:
        leg.observe(v)
    leg.finalize(min_uses=2, min_chars_saved=1)
    assert leg.encode_prefix("src/foo/thing.py").startswith("@")
    out = leg.write()
    leg2 = Legends.read(out, prefix="@")
    encoded = leg.encode_prefix("src/foo/a.py")
    decoded = leg2.decode_prefix(encoded)
    assert decoded == "src/foo/a.py"


def test_legend_literal_at_digit_not_corrupted():
    """A literal value that starts with the prefix + a digit (e.g. a '@2x'
    retina asset path or a '@1.2.3' version token) must not be mistaken for a
    legend handle on decode. Regression for the encode/decode asymmetry:
    encode_prefix left such literals verbatim, but decode_prefix expanded any
    '@<digits>' token, silently rewriting the value to legend[N] + suffix.
    """
    leg = Legends(prefix="@")
    # Build a populated legend so handle indices exist to collide with.
    for v in ["src/module/handlers.py", "src/module/handlers.py", "src/module/"]:
        leg.observe(v)
    leg.finalize(min_uses=2, min_chars_saved=1)
    out = leg.write()
    leg2 = Legends.read(out, prefix="@")

    # Real legend prefix still interns + round-trips.
    handle = leg.encode_prefix("src/module/handlers.py")
    assert handle.startswith("@")
    assert leg2.decode_prefix(handle) == "src/module/handlers.py"

    # Literal @-leading values survive verbatim, including the double-prefix edge.
    for literal in ["@2x_asset", "@1abc", "@1.2.3", "@10", "@@already", "@foo"]:
        enc = leg.encode_prefix(literal)
        assert leg2.decode_prefix(enc) == literal, (
            f"{literal!r} corrupted: encoded {enc!r} decoded {leg2.decode_prefix(enc)!r}"
        )


def test_assemble_and_split():
    header = write_header("demo", "gen1")
    payload = assemble(header, "@1=x/", "k=v", "c,row1")
    head, blocks = split_sections(payload)
    assert head == header
    assert blocks == ["@1=x/", "k=v", "c,row1"]
