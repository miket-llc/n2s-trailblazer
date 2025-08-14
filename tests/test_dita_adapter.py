"""Test DITA adapter XML parsing functionality."""

import pytest
from pathlib import Path
import tempfile
from lxml import etree  # type: ignore

from trailblazer.adapters.dita import (
    parse_topic,
    parse_map,
    is_dita_file,
    compute_file_sha256,
    TopicDoc,
    MapDoc,
    _generate_topic_id,
    _generate_map_id,
    _extract_labels_from_prolog,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_topic_xml():
    """Sample DITA topic XML content."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE concept PUBLIC "-//OASIS//DTD DITA Concept//EN" "concept.dtd">
<concept id="sample_concept" xml:lang="en-US">
    <title>Sample Concept Topic</title>
    <prolog>
        <metadata>
            <keywords>
                <keyword>test</keyword>
                <keyword>sample</keyword>
            </keywords>
            <othermeta name="audience" content="admin"/>
            <othermeta name="product" content="ellucian"/>
        </metadata>
    </prolog>
    <conbody>
        <p>This is a sample concept with an image:</p>
        <p>
            <image href="images/sample.png" alt="Sample image">
                <alt>Alternative text for sample image</alt>
            </image>
        </p>
        <p>And an external link: <xref href="https://example.com">Example</xref></p>
        <p>Key reference: <keyword keyref="product-name"/>.</p>
        <object data="files/document.pdf" type="application/pdf"/>
    </conbody>
</concept>"""


@pytest.fixture
def sample_map_xml():
    """Sample DITA map XML content."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE map PUBLIC "-//OASIS//DTD DITA Map//EN" "map.dtd">
<map id="user_guide" xml:lang="en-US">
    <title>User Guide</title>
    <prolog>
        <metadata>
            <keywords>
                <keyword>documentation</keyword>
                <keyword>user-guide</keyword>
            </keywords>
        </metadata>
    </prolog>
    <keydef keys="product-name" href="concepts/product.dita"/>
    <keydef keys="company-name" href="concepts/company.dita"/>
    <topicref href="concepts/introduction.dita" navtitle="Introduction">
        <topicref href="concepts/getting-started.dita" navtitle="Getting Started"/>
        <topicref href="tasks/setup.dita" navtitle="Setup"/>
    </topicref>
    <topicref href="reference/api.dita" navtitle="API Reference"/>
</map>"""


def test_generate_topic_id():
    """Test topic ID generation."""
    assert _generate_topic_id("concepts/intro.dita") == "topic:concepts/intro"
    assert _generate_topic_id("Concepts/Intro.DITA") == "topic:concepts/intro"
    assert _generate_topic_id("intro.xml", "my-id") == "topic:intro#my-id"


def test_generate_map_id():
    """Test map ID generation."""
    assert _generate_map_id("maps/user-guide.ditamap") == "map:maps/user-guide"
    assert _generate_map_id("User-Guide.DITAMAP") == "map:user-guide"


def test_is_dita_file(temp_dir):
    """Test DITA file detection."""
    # DITA extension files
    dita_file = temp_dir / "test.dita"
    dita_file.write_text(
        "<?xml version='1.0'?><topic><title>Test</title></topic>"
    )
    assert is_dita_file(dita_file)

    ditamap_file = temp_dir / "test.ditamap"
    ditamap_file.write_text(
        "<?xml version='1.0'?><map><title>Test</title></map>"
    )
    assert is_dita_file(ditamap_file)

    # XML file with DITA content
    xml_file = temp_dir / "test.xml"
    xml_file.write_text(
        '<?xml version="1.0"?><!DOCTYPE concept><concept><title>Test</title></concept>'
    )
    assert is_dita_file(xml_file)

    # Non-DITA file
    txt_file = temp_dir / "test.txt"
    txt_file.write_text("Regular text file")
    assert not is_dita_file(txt_file)

    # Non-existent file
    assert not is_dita_file(temp_dir / "nonexistent.dita")


def test_compute_file_sha256(temp_dir):
    """Test file SHA256 computation."""
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")

    sha256 = compute_file_sha256(test_file)
    assert len(sha256) == 64
    assert sha256 == compute_file_sha256(test_file)  # Deterministic


def test_extract_labels_from_prolog(sample_topic_xml):
    """Test label extraction from prolog."""
    tree = etree.fromstring(sample_topic_xml.encode("utf-8"))
    prolog = tree.find("prolog")

    labels = _extract_labels_from_prolog(prolog)

    expected_labels = ["audience:admin", "product:ellucian", "sample", "test"]
    assert sorted(labels) == sorted(expected_labels)


def test_parse_topic(temp_dir, sample_topic_xml):
    """Test topic parsing."""
    topic_file = temp_dir / "sample.dita"
    topic_file.write_text(sample_topic_xml)

    doc = parse_topic(topic_file)

    assert isinstance(doc, TopicDoc)
    assert doc.title == "Sample Concept Topic"
    assert doc.doctype == "concept"
    assert "topic:sample" in doc.id  # May include element ID

    # Check labels
    expected_labels = ["audience:admin", "product:ellucian", "sample", "test"]
    assert sorted(doc.labels) == sorted(expected_labels)

    # Check media references
    assert len(doc.images) == 2  # One image, one object

    image_ref = next(
        (ref for ref in doc.images if ref.media_type == "image"), None
    )
    assert image_ref is not None
    assert image_ref.filename == "images/sample.png"
    assert image_ref.alt == "Sample image"

    object_ref = next(
        (ref for ref in doc.images if ref.media_type == "application/pdf"),
        None,
    )
    assert object_ref is not None
    assert object_ref.filename == "files/document.pdf"

    # Check cross-references
    assert "https://example.com" in doc.xrefs

    # Check key references
    assert "product-name" in doc.keyrefs

    # Check body XML is present
    assert "<conbody>" in doc.body_xml
    assert "Sample image" in doc.body_xml


def test_parse_map(temp_dir, sample_map_xml):
    """Test map parsing."""
    map_file = temp_dir / "user-guide.ditamap"
    map_file.write_text(sample_map_xml)

    doc = parse_map(map_file)

    assert isinstance(doc, MapDoc)
    assert doc.title == "User Guide"
    assert doc.id == "map:user-guide"  # Will be updated by caller

    # Check key definitions
    assert "product-name" in doc.keydefs
    assert doc.keydefs["product-name"] == "concepts/product.dita"
    assert "company-name" in doc.keydefs

    # Check hierarchy
    assert len(doc.hierarchy) >= 4  # Should have all topicref elements

    intro_ref = next(
        (
            ref
            for ref in doc.hierarchy
            if ref.href == "concepts/introduction.dita"
        ),
        None,
    )
    assert intro_ref is not None
    assert intro_ref.navtitle == "Introduction"

    # Check labels
    expected_labels = ["documentation", "user-guide"]
    assert sorted(doc.labels) == sorted(expected_labels)


def test_parse_topic_with_element_id(temp_dir):
    """Test topic parsing with element ID."""
    topic_xml = """<?xml version="1.0"?>
    <topic id="element-id">
        <title>Topic with Element ID</title>
        <body><p>Content</p></body>
    </topic>"""

    topic_file = temp_dir / "test.dita"
    topic_file.write_text(topic_xml)

    doc = parse_topic(topic_file)
    assert "element-id" in doc.id  # Should include element ID


def test_parse_task_topic(temp_dir):
    """Test parsing task-type topic."""
    task_xml = """<?xml version="1.0"?>
    <!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd">
    <task id="sample_task">
        <title>Sample Task</title>
        <taskbody>
            <prereq>Prerequisites here.</prereq>
            <steps>
                <step><cmd>First step.</cmd></step>
                <step><cmd>Second step.</cmd></step>
            </steps>
        </taskbody>
    </task>"""

    task_file = temp_dir / "sample-task.dita"
    task_file.write_text(task_xml)

    doc = parse_topic(task_file)
    assert doc.doctype == "task"
    assert "taskbody" in doc.body_xml
    assert "First step" in doc.body_xml


def test_parse_reference_topic(temp_dir):
    """Test parsing reference-type topic."""
    ref_xml = """<?xml version="1.0"?>
    <!DOCTYPE reference PUBLIC "-//OASIS//DTD DITA Reference//EN" "reference.dtd">
    <reference id="api_ref">
        <title>API Reference</title>
        <refbody>
            <section>
                <title>Methods</title>
                <p>Available methods...</p>
            </section>
        </refbody>
    </reference>"""

    ref_file = temp_dir / "api-ref.dita"
    ref_file.write_text(ref_xml)

    doc = parse_topic(ref_file)
    assert doc.doctype == "reference"
    assert "refbody" in doc.body_xml


def test_parse_topic_with_conrefs(temp_dir):
    """Test topic with content references."""
    topic_xml = """<?xml version="1.0"?>
    <topic id="with_conrefs">
        <title>Topic with Content References</title>
        <body>
            <p conref="shared.dita#shared/disclaimer">Disclaimer text</p>
            <p>Regular content</p>
        </body>
    </topic>"""

    topic_file = temp_dir / "conrefs.dita"
    topic_file.write_text(topic_xml)

    doc = parse_topic(topic_file)
    assert "shared.dita#shared/disclaimer" in doc.conrefs


def test_parse_map_with_nested_refs(temp_dir):
    """Test map with nested topic references."""
    map_xml = """<?xml version="1.0"?>
    <map id="nested_map">
        <title>Nested Map</title>
        <topicref href="section1.dita" navtitle="Section 1">
            <topicref href="subsection1a.dita" navtitle="Subsection 1A"/>
            <topicref href="subsection1b.dita" navtitle="Subsection 1B">
                <topicref href="subsection1b1.dita" navtitle="Subsection 1B1"/>
            </topicref>
        </topicref>
        <topicref href="section2.dita" navtitle="Section 2"/>
    </map>"""

    map_file = temp_dir / "nested.ditamap"
    map_file.write_text(map_xml)

    doc = parse_map(map_file)

    # Should capture all nested references
    hrefs = [ref.href for ref in doc.hierarchy if ref.href]
    expected_hrefs = [
        "section1.dita",
        "subsection1a.dita",
        "subsection1b.dita",
        "subsection1b1.dita",
        "section2.dita",
    ]

    for expected_href in expected_hrefs:
        assert expected_href in hrefs


def test_media_extraction_order(temp_dir):
    """Test that media references maintain order."""
    topic_xml = """<?xml version="1.0"?>
    <topic id="media_order">
        <title>Media Order Test</title>
        <body>
            <p>First image: <image href="image1.png" alt="First"/></p>
            <p>Second image: <image href="image2.jpg" alt="Second"/></p>
            <p>A file: <object data="file1.pdf" type="application/pdf"/></p>
            <p>Third image: <image href="image3.gif" alt="Third"/></p>
        </body>
    </topic>"""

    topic_file = temp_dir / "media-order.dita"
    topic_file.write_text(topic_xml)

    doc = parse_topic(topic_file)

    # Should have 4 media references in order
    assert len(doc.images) == 4

    media_by_order = sorted(doc.images, key=lambda x: x.order)

    assert media_by_order[0].filename == "image1.png"
    assert media_by_order[0].order == 1
    assert media_by_order[1].filename == "image2.jpg"
    assert media_by_order[1].order == 2
    assert media_by_order[2].filename == "file1.pdf"
    assert media_by_order[2].order == 3
    assert media_by_order[3].filename == "image3.gif"
    assert media_by_order[3].order == 4


def test_parse_malformed_xml_recovery(temp_dir):
    """Test parsing of malformed XML with recovery."""
    malformed_xml = """<?xml version="1.0"?>
    <topic id="malformed">
        <title>Malformed Topic</title>
        <body>
            <p>Unclosed tag here
            <p>Another paragraph</p>
        </body>
    </topic>"""

    topic_file = temp_dir / "malformed.dita"
    topic_file.write_text(malformed_xml)

    # Should not raise exception due to recovery parser
    doc = parse_topic(topic_file)
    assert doc.title == "Malformed Topic"


def test_empty_prolog_labels(temp_dir):
    """Test topic with no prolog/metadata."""
    simple_xml = """<?xml version="1.0"?>
    <topic id="simple">
        <title>Simple Topic</title>
        <body><p>Simple content</p></body>
    </topic>"""

    topic_file = temp_dir / "simple.dita"
    topic_file.write_text(simple_xml)

    doc = parse_topic(topic_file)
    assert doc.labels == []


def test_map_without_keydefs(temp_dir):
    """Test map without key definitions."""
    map_xml = """<?xml version="1.0"?>
    <map id="simple_map">
        <title>Simple Map</title>
        <topicref href="topic1.dita"/>
        <topicref href="topic2.dita"/>
    </map>"""

    map_file = temp_dir / "simple.ditamap"
    map_file.write_text(map_xml)

    doc = parse_map(map_file)
    assert doc.keydefs == {}
    assert len(doc.hierarchy) == 2
