# Test constants for magic numbers
EXPECTED_COUNT_2 = 2
EXPECTED_COUNT_3 = 3
EXPECTED_COUNT_4 = 4

"""Test DITA adapter XML parsing functionality."""

import tempfile
from pathlib import Path

import pytest
from lxml import etree  # type: ignore

from trailblazer.adapters.dita import (
    MapDoc,
    TopicDoc,
    _classify_link_type,
    _extract_enhanced_metadata_from_prolog,
    _extract_labels_from_prolog,
    _extract_links_from_element,
    _generate_map_id,
    _generate_topic_id,
    _normalize_url,
    _resolve_dita_reference,
    compute_file_sha256,
    is_dita_file,
    parse_map,
    parse_topic,
)

# Mark all tests as unit tests (no database needed)
pytestmark = pytest.mark.unit


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
    dita_file.write_text("<?xml version='1.0'?><topic><title>Test</title></topic>")
    assert is_dita_file(dita_file)

    ditamap_file = temp_dir / "test.ditamap"
    ditamap_file.write_text("<?xml version='1.0'?><map><title>Test</title></map>")
    assert is_dita_file(ditamap_file)

    # XML file with DITA content
    xml_file = temp_dir / "test.xml"
    xml_file.write_text('<?xml version="1.0"?><!DOCTYPE concept><concept><title>Test</title></concept>')
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

    image_ref = next((ref for ref in doc.images if ref.media_type == "image"), None)
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
        (ref for ref in doc.hierarchy if ref.href == "concepts/introduction.dita"),
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
    assert len(doc.images) == EXPECTED_COUNT_4

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
    assert len(doc.hierarchy) == EXPECTED_COUNT_2


# Test enhanced metadata extraction
def test_extract_enhanced_metadata_from_prolog():
    """Test enhanced metadata extraction from prolog."""
    prolog_xml = """<prolog>
        <metadata>
            <keywords>
                <keyword>api</keyword>
                <keyword>reference</keyword>
            </keywords>
            <othermeta name="status" content="reviewed"/>
        </metadata>
        <resourceid appname="MyApp"/>
        <critdates created="2023-01-15" modified="2023-03-20"/>
        <author>John Doe</author>
        <authorinformation>
            <personname>
                <firstname>Jane</firstname>
                <lastname>Smith</lastname>
            </personname>
        </authorinformation>
        <data name="version" value="1.2"/>
    </prolog>"""

    tree = etree.fromstring(prolog_xml.encode("utf-8"))
    metadata = _extract_enhanced_metadata_from_prolog(tree)

    assert metadata["keywords"] == ["api", "reference"]
    assert metadata["resource_app"] == "MyApp"
    assert metadata["critdates"]["created"] == "2023-01-15"
    assert metadata["critdates"]["modified"] == "2023-03-20"
    assert "John Doe" in metadata["authors"]
    assert "Jane Smith" in metadata["authors"]
    assert metadata["data_pairs"]["version"] == "1.2"


def test_extract_enhanced_metadata_with_attributes():
    """Test enhanced metadata extraction with audience/product attributes."""
    prolog_xml = """<prolog>
        <metadata audience="implementer" product="Navigate" platform="SaaS" otherprops="status=approved">
            <keywords>
                <keyword>configuration</keyword>
            </keywords>
        </metadata>
    </prolog>"""

    tree = etree.fromstring(prolog_xml.encode("utf-8"))
    metadata = _extract_enhanced_metadata_from_prolog(tree)

    assert metadata["audience"] == "implementer"
    assert metadata["product"] == "Navigate"
    assert metadata["platform"] == "SaaS"
    assert metadata["otherprops"]["status"] == "approved"
    assert metadata["keywords"] == ["configuration"]


def test_normalize_url():
    """Test URL normalization functionality."""
    # Test tracking parameter removal
    url_with_tracking = "https://example.com/page?utm_source=test&utm_medium=email&content=actual"
    normalized = _normalize_url(url_with_tracking)
    assert "utm_source" not in normalized
    assert "utm_medium" not in normalized
    assert "content=actual" in normalized

    # Test anchor preservation
    url_with_anchor = "https://example.com/page#section1"
    normalized = _normalize_url(url_with_anchor)
    assert "#section1" in normalized

    # Test empty/None handling
    assert _normalize_url("") == ""
    assert _normalize_url(None) is None


def test_classify_link_type():
    """Test link type classification."""
    # External HTTP links
    assert _classify_link_type("https://example.com") == "external"
    assert _classify_link_type("http://example.com") == "external"

    # Confluence links
    assert _classify_link_type("https://mycompany.confluence.com/page") == "confluence"
    assert _classify_link_type("https://mycompany.atlassian.net/wiki") == "confluence"

    # DITA internal links
    assert _classify_link_type("concepts/intro.dita") == "dita"
    assert _classify_link_type("maps/user-guide.ditamap") == "dita"
    assert _classify_link_type("reference.xml") == "dita"

    # Key references
    assert _classify_link_type("product-key", is_keyref=True) == "dita"

    # Other external
    assert _classify_link_type("mailto:test@example.com") == "external"
    assert _classify_link_type("ftp://files.example.com") == "external"


def test_resolve_dita_reference(temp_dir):
    """Test DITA reference resolution."""
    # Create a simple file structure
    concepts_dir = temp_dir / "concepts"
    concepts_dir.mkdir()
    intro_file = concepts_dir / "intro.dita"
    intro_file.write_text("<?xml version='1.0'?><topic><title>Intro</title></topic>")

    current_file = temp_dir / "current.dita"

    # Test relative reference resolution
    resolved = _resolve_dita_reference("concepts/intro.dita", current_file, temp_dir)
    assert resolved == "topic:concepts/intro"

    # Test with anchor
    resolved = _resolve_dita_reference("concepts/intro.dita#section1", current_file, temp_dir)
    assert resolved == "topic:concepts/intro#section1"

    # Test map reference
    resolved = _resolve_dita_reference("concepts/intro.ditamap", current_file, temp_dir)
    assert resolved == "map:concepts/intro"

    # Test reference (doesn't need to exist)
    resolved = _resolve_dita_reference("nonexistent/file.dita", current_file, temp_dir)
    assert resolved == "topic:nonexistent/file"

    # Test external URL (should return None)
    resolved = _resolve_dita_reference("https://example.com", current_file, temp_dir)
    assert resolved is None


def test_extract_links_from_element(temp_dir):
    """Test comprehensive link extraction from XML elements."""
    xml_content = """<topic>
        <body>
            <p>External link: <xref href="https://example.com">Example</xref></p>
            <p>Internal link: <xref href="concepts/intro.dita">Introduction</xref></p>
            <p>Key reference: <xref keyref="product-name">Product</xref></p>
            <p>Link element: <link href="https://docs.example.com">Documentation</link></p>
            <p conref="shared.dita#shared/disclaimer">Disclaimer</p>
            <p>Content key ref: <ph conkeyref="keys/company-name">Company</ph></p>
        </body>
    </topic>"""

    tree = etree.fromstring(xml_content.encode("utf-8"))
    current_file = temp_dir / "test.dita"

    # Create referenced file for resolution testing
    concepts_dir = temp_dir / "concepts"
    concepts_dir.mkdir()
    intro_file = concepts_dir / "intro.dita"
    intro_file.write_text("<?xml version='1.0'?><topic><title>Intro</title></topic>")

    links = _extract_links_from_element(tree, current_file, temp_dir)

    # Should extract all link types
    assert len(links) >= 6

    # Check external links
    external_links = [link for link in links if link.target_type == "external"]
    assert len(external_links) == EXPECTED_COUNT_2
    assert any(link.target_url == "https://example.com" for link in external_links)
    assert any(link.target_url == "https://docs.example.com" for link in external_links)

    # Check DITA internal links
    dita_links = [link for link in links if link.target_type == "dita" and link.href]
    assert len(dita_links) >= 1
    assert any(link.target_page_id == "topic:concepts/intro" for link in dita_links)

    # Check key references
    key_refs = [link for link in links if link.keyref]
    assert len(key_refs) >= 2
    assert any(link.keyref == "product-name" for link in key_refs)
    assert any(link.keyref == "keys/company-name" for link in key_refs)

    # Check content references
    conrefs = [link for link in links if link.element_type in ("conref", "conkeyref")]
    assert len(conrefs) >= 2
    assert any(link.conref == "shared.dita" for link in conrefs)


def test_parse_topic_enhanced_features(temp_dir):
    """Test topic parsing with enhanced metadata and links."""
    topic_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <concept id="enhanced_concept" xml:lang="en-US">
        <title>Enhanced Concept Topic</title>
        <prolog>
            <metadata audience="implementer" product="Navigate" platform="SaaS">
                <keywords>
                    <keyword>configuration</keyword>
                    <keyword>setup</keyword>
                </keywords>
            </metadata>
            <resourceid appname="ConfigApp"/>
            <critdates created="2023-01-15" modified="2023-03-20"/>
            <author>Technical Writer</author>
        </prolog>
        <conbody>
            <p>See also: <xref href="related-topic.dita">Related Topic</xref></p>
            <p>External ref: <xref href="https://docs.example.com">Documentation</xref></p>
            <p>Key ref: <xref keyref="product-name">Product Name</xref></p>
        </conbody>
    </concept>"""

    topic_file = temp_dir / "enhanced.dita"
    topic_file.write_text(topic_xml)

    doc = parse_topic(topic_file)

    # Check enhanced metadata
    assert hasattr(doc, "enhanced_metadata")
    assert doc.enhanced_metadata["audience"] == "implementer"
    assert doc.enhanced_metadata["product"] == "Navigate"
    assert doc.enhanced_metadata["platform"] == "SaaS"
    assert "configuration" in doc.enhanced_metadata["keywords"]
    assert "setup" in doc.enhanced_metadata["keywords"]
    assert doc.enhanced_metadata["resource_app"] == "ConfigApp"
    assert doc.enhanced_metadata["critdates"]["created"] == "2023-01-15"
    assert "Technical Writer" in doc.enhanced_metadata["authors"]

    # Check enhanced links
    assert hasattr(doc, "links")
    assert len(doc.links) >= 3

    # Find specific link types
    external_links = [link for link in doc.links if link.target_type == "external"]
    dita_links = [link for link in doc.links if link.target_type == "dita" and link.href]
    key_refs = [link for link in doc.links if link.keyref]

    assert len(external_links) >= 1
    assert len(dita_links) >= 1
    assert len(key_refs) >= 1

    # Check specific links
    assert any(link.target_url == "https://docs.example.com" for link in external_links)
    assert any(link.href == "related-topic.dita" for link in dita_links)
    assert any(link.keyref == "product-name" for link in key_refs)


def test_parse_map_enhanced_features(temp_dir):
    """Test map parsing with enhanced metadata and links."""
    map_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <map id="enhanced_map" xml:lang="en-US">
        <title>Enhanced User Guide</title>
        <prolog>
            <metadata audience="end-user" product="Navigate">
                <keywords>
                    <keyword>user-guide</keyword>
                    <keyword>documentation</keyword>
                </keywords>
            </metadata>
            <author>Documentation Team</author>
        </prolog>
        <keydef keys="product-name" href="concepts/product.dita"/>
        <topicref href="introduction.dita" navtitle="Introduction">
            <topicref href="getting-started.dita" navtitle="Getting Started"/>
        </topicref>
        <topicref href="https://support.example.com" navtitle="External Support" scope="external"/>
    </map>"""

    map_file = temp_dir / "enhanced.ditamap"
    map_file.write_text(map_xml)

    doc = parse_map(map_file)

    # Check enhanced metadata
    assert hasattr(doc, "enhanced_metadata")
    assert doc.enhanced_metadata["audience"] == "end-user"
    assert doc.enhanced_metadata["product"] == "Navigate"
    assert "user-guide" in doc.enhanced_metadata["keywords"]
    assert "Documentation Team" in doc.enhanced_metadata["authors"]

    # Check enhanced links
    assert hasattr(doc, "links")

    # Should extract links from topicref elements
    external_links = [link for link in doc.links if link.target_type == "external"]
    assert len(external_links) >= 1
    assert any("support.example.com" in link.target_url for link in external_links)
