"""tests/test_diff.py — Unit tests for watchkit.diff."""

import unittest

from watchkit.diff import (
    content_hash,
    diff_excerpt,
    has_changed,
    item_hash,
    normalise,
    strip_tags,
)


class TestStripTags(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(strip_tags("hello world"), "hello world")

    def test_simple_tags_removed(self):
        result = strip_tags("<b>bold</b> and <i>italic</i>")
        self.assertIn("bold", result)
        self.assertIn("italic", result)
        self.assertNotIn("<b>", result)
        self.assertNotIn("<i>", result)

    def test_html_entities_in_tags_decoded(self):
        # Entities inside actual HTML markup are decoded by the parser
        result = strip_tags("<p>caf&eacute;</p>")
        self.assertIn("café", result)

    def test_no_tags_passthrough_entities(self):
        # Plain text without any angle brackets passes through unchanged
        text = "AT&T and Python 3.12 is great"
        result = strip_tags(text)
        self.assertEqual(result, text)

    def test_no_tags_passthrough(self):
        text = "just plain text 123"
        self.assertEqual(strip_tags(text), text)


class TestNormalise(unittest.TestCase):
    def test_whitespace_collapsed(self):
        result = normalise("  foo   bar\n\nbaz  ")
        self.assertEqual(result, "foo bar baz")

    def test_html_stripped(self):
        result = normalise("<p>Hello <strong>world</strong></p>")
        self.assertNotIn("<p>", result)
        self.assertIn("Hello", result)
        self.assertIn("world", result)

    def test_volatile_tokens_removed(self):
        result = normalise("foo TOKEN123 bar", volatile_tokens=["TOKEN123"])
        self.assertNotIn("TOKEN123", result)
        self.assertIn("foo", result)
        self.assertIn("bar", result)

    def test_empty_string(self):
        self.assertEqual(normalise(""), "")

    def test_only_whitespace(self):
        self.assertEqual(normalise("   \n\t  "), "")


class TestContentHash(unittest.TestCase):
    def test_same_text_same_hash(self):
        h1 = content_hash("hello world")
        h2 = content_hash("hello world")
        self.assertEqual(h1, h2)

    def test_different_text_different_hash(self):
        h1 = content_hash("hello world")
        h2 = content_hash("goodbye world")
        self.assertNotEqual(h1, h2)

    def test_whitespace_insensitive(self):
        h1 = content_hash("hello  world")
        h2 = content_hash("hello world")
        self.assertEqual(h1, h2)

    def test_html_tag_insensitive(self):
        h1 = content_hash("<p>hello</p>")
        h2 = content_hash("hello")
        self.assertEqual(h1, h2)

    def test_hash_length(self):
        h = content_hash("some content")
        self.assertEqual(len(h), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_volatile_token_stripped(self):
        # Token is removed before whitespace collapsing, so the result normalises cleanly
        h1 = content_hash("hello CSRF_TOKEN_ABC world", volatile_tokens=["CSRF_TOKEN_ABC"])
        h2 = content_hash("hello world")
        self.assertEqual(h1, h2)


class TestItemHash(unittest.TestCase):
    def test_same_inputs_same_hash(self):
        h1 = item_hash("title", "body text")
        h2 = item_hash("title", "body text")
        self.assertEqual(h1, h2)

    def test_changed_title_changes_hash(self):
        h1 = item_hash("title A", "body")
        h2 = item_hash("title B", "body")
        self.assertNotEqual(h1, h2)

    def test_changed_body_changes_hash(self):
        h1 = item_hash("title", "body A")
        h2 = item_hash("title", "body B")
        self.assertNotEqual(h1, h2)


class TestHasChanged(unittest.TestCase):
    def test_first_observation_not_a_change(self):
        """stored_hash=None means first run; should not trigger an event."""
        self.assertFalse(has_changed("abcdef", None))

    def test_same_hash_no_change(self):
        self.assertFalse(has_changed("abcdef", "abcdef"))

    def test_different_hash_is_change(self):
        self.assertTrue(has_changed("abcdef", "123456"))


class TestDiffExcerpt(unittest.TestCase):
    def test_identical_texts_empty_diff(self):
        result = diff_excerpt("hello world", "hello world")
        self.assertEqual(result, "")

    def test_different_texts_non_empty_diff(self):
        result = diff_excerpt("line one\nline two", "line one\nline three")
        self.assertIn("-", result)
        self.assertIn("+", result)

    def test_whitespace_diff_treated_as_equal(self):
        """Extra whitespace should be normalised away → no diff."""
        result = diff_excerpt("hello   world", "hello world")
        self.assertEqual(result, "")

    def test_max_lines_respected(self):
        old = "\n".join(f"line {i}" for i in range(100))
        new = "\n".join(f"line {i} modified" for i in range(100))
        result = diff_excerpt(old, new, max_lines=10)
        lines = result.splitlines()
        self.assertLessEqual(len(lines), 11)  # 10 + "truncated" line

    def test_new_content_appears_in_diff(self):
        result = diff_excerpt("old content", "new content")
        self.assertIn("new content", result)


if __name__ == "__main__":
    unittest.main()
