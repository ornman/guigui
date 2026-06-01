"""Tests for src.notify — XML escaping."""

from src.notify import _xml_escape


class TestXmlEscape:
    def test_ampersand(self):
        assert _xml_escape("a&b") == "a&amp;b"

    def test_angle_brackets(self):
        assert _xml_escape("<>") == "&lt;&gt;"

    def test_quotes(self):
        assert _xml_escape('"x"') == "&quot;x&quot;"
        assert _xml_escape("'y'") == "&apos;y&apos;"

    def test_chinese_characters(self):
        # Non-ASCII characters should be encoded as &#xHH;
        result = _xml_escape("中文")
        assert "&#x" in result
        assert "中文" not in result

    def test_ascii_passes_through(self):
        assert _xml_escape("hello") == "hello"

    def test_mixed(self):
        result = _xml_escape("a&b<c>中文")
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&#x" in result
