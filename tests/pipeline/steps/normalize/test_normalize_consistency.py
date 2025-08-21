from trailblazer.pipeline.steps.normalize.html_to_md import (
    _to_markdown_from_storage,
    _to_markdown_from_adf,
)


def test_markdown_whitespace_consistency():
    """Test that markdown output has consistent whitespace and heading style."""

    # Test storage format
    xhtml = "<h1>Title</h1><p>Content with\r\n\r\nline breaks.</p><h2>Subtitle</h2><p>More content.</p>"
    md_storage = _to_markdown_from_storage(xhtml)

    # Should normalize line endings and limit consecutive newlines
    assert "\r" not in md_storage
    assert "\n\n\n" not in md_storage
    assert md_storage.startswith("# Title")
    assert "## Subtitle" in md_storage

    # Test ADF format
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Title"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Content with breaks."}],
            },
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Subtitle"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "More content."}],
            },
        ],
    }
    md_adf = _to_markdown_from_adf(adf)

    # Should use ATX heading style and normalize whitespace
    assert "\n\n\n" not in md_adf
    assert md_adf.startswith("# Title")
    assert "## Subtitle" in md_adf

    # Both should strip leading/trailing whitespace
    assert not md_storage.startswith(" ")
    assert not md_storage.endswith(" ")
    assert not md_adf.startswith(" ")
    assert not md_adf.endswith(" ")
