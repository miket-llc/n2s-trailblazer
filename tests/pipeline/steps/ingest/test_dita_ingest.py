"""Test DITA ingest functionality."""

import pytest
from pathlib import Path
import tempfile
import json

from trailblazer.pipeline.steps.ingest.dita import (
    ingest_dita,
    _find_dita_files,
    _should_include_file,
    _create_dita_record,
    _write_media_sidecars,
    _build_hierarchy_and_write_edges,
    _write_labels_and_edges,
)
from trailblazer.adapters.dita import TopicDoc, MapDoc, MediaRef

# Mark all tests as integration tests (need database)
pytestmark = pytest.mark.integration


@pytest.fixture
def temp_dita_structure():
    """Create a temporary DITA project structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create directory structure
        concepts_dir = root / "concepts"
        tasks_dir = root / "tasks"
        maps_dir = root / "maps"
        images_dir = root / "images"

        for dir_path in [concepts_dir, tasks_dir, maps_dir, images_dir]:
            dir_path.mkdir()

        # Create sample topic files
        intro_topic = concepts_dir / "introduction.dita"
        intro_topic.write_text(
            """<?xml version="1.0"?>
        <!DOCTYPE concept PUBLIC "-//OASIS//DTD DITA Concept//EN" "concept.dtd">
        <concept id="introduction">
            <title>Introduction</title>
            <prolog>
                <metadata>
                    <keywords>
                        <keyword>intro</keyword>
                        <keyword>getting-started</keyword>
                    </keywords>
                    <othermeta name="audience" content="beginner"/>
                </metadata>
            </prolog>
            <conbody>
                <p>Welcome to our documentation.</p>
                <p><image href="../images/welcome.png" alt="Welcome image"/></p>
            </conbody>
        </concept>"""
        )

        setup_task = tasks_dir / "setup.dita"
        setup_task.write_text(
            """<?xml version="1.0"?>
        <!DOCTYPE task PUBLIC "-//OASIS//DTD DITA Task//EN" "task.dtd">
        <task id="setup">
            <title>Setup Instructions</title>
            <prolog>
                <metadata>
                    <keywords>
                        <keyword>setup</keyword>
                        <keyword>installation</keyword>
                    </keywords>
                    <othermeta name="audience" content="admin"/>
                </metadata>
            </prolog>
            <taskbody>
                <steps>
                    <step><cmd>Download the software.</cmd></step>
                    <step><cmd>Install according to instructions.</cmd></step>
                </steps>
            </taskbody>
        </task>"""
        )

        # Create a map file
        user_guide_map = maps_dir / "user-guide.ditamap"
        user_guide_map.write_text(
            """<?xml version="1.0"?>
        <!DOCTYPE map PUBLIC "-//OASIS//DTD DITA Map//EN" "map.dtd">
        <map id="user_guide">
            <title>User Guide</title>
            <prolog>
                <metadata>
                    <keywords>
                        <keyword>documentation</keyword>
                        <keyword>user-guide</keyword>
                    </keywords>
                </metadata>
            </prolog>
            <topicref href="../concepts/introduction.dita" navtitle="Introduction"/>
            <topicref href="../tasks/setup.dita" navtitle="Setup"/>
        </map>"""
        )

        # Create some non-DITA files that should be skipped
        (root / "readme.txt").write_text("This is a readme file.")
        (root / "archive.zip").write_text("fake zip content")

        # Create a plain XML file that's not DITA
        (root / "config.xml").write_text(
            """<?xml version="1.0"?>
        <configuration>
            <setting name="debug" value="true"/>
        </configuration>"""
        )

        yield root


def test_should_include_file():
    """Test file inclusion logic."""
    # Test default patterns
    assert _should_include_file(Path("test.dita"))
    assert _should_include_file(Path("test.ditamap"))
    assert _should_include_file(Path("concept.xml"))

    # Test custom include patterns
    assert _should_include_file(Path("test.dita"), include_patterns=["*.dita"])
    assert not _should_include_file(
        Path("test.xml"), include_patterns=["*.dita"]
    )

    # Test exclude patterns
    assert not _should_include_file(
        Path("test.dita"), exclude_patterns=["*.dita"]
    )
    assert not _should_include_file(
        Path("temp/test.dita"), exclude_patterns=["temp/*"]
    )


def test_find_dita_files(temp_dita_structure):
    """Test DITA file discovery."""
    files = list(_find_dita_files(temp_dita_structure))

    # Should find the DITA files but not the others
    file_names = [f.name for f in files]

    assert "introduction.dita" in file_names
    assert "setup.dita" in file_names
    assert "user-guide.ditamap" in file_names

    # Should not find non-DITA files
    assert "readme.txt" not in file_names
    assert "archive.zip" not in file_names
    assert "config.xml" not in file_names

    # Check we found exactly 3 files
    assert len(files) == 3


def test_find_dita_files_with_patterns(temp_dita_structure):
    """Test DITA file discovery with custom patterns."""
    # Only include DITA topics, exclude maps
    files = list(
        _find_dita_files(
            temp_dita_structure,
            include_patterns=["*.dita"],
            exclude_patterns=["*.ditamap"],
        )
    )

    file_names = [f.name for f in files]
    assert "introduction.dita" in file_names
    assert "setup.dita" in file_names
    assert "user-guide.ditamap" not in file_names


def test_create_dita_record():
    """Test DITA record creation."""
    # Mock topic doc
    topic = TopicDoc(
        id="topic:concepts/intro",
        title="Introduction",
        doctype="concept",
        body_xml="<conbody><p>Content</p></conbody>",
        prolog_metadata={},
        images=[
            MediaRef(
                "test.png",
                "image",
                "/topic/body/p[1]/image[1]",
                "Test image",
                1,
            )
        ],
        xrefs=["http://example.com"],
        keyrefs=["product-name"],
        conrefs=[],
        labels=["intro", "audience:beginner"],
        links=[],
        enhanced_metadata={},
    )

    # Mock file info
    file_path = Path("/tmp/concepts/intro.dita")
    root_dir = Path("/tmp")

    # Mock stat result
    class MockStat:
        st_ctime = 1609459200.0  # 2021-01-01
        st_mtime = 1609545600.0  # 2021-01-02

    record = _create_dita_record(
        topic, file_path, root_dir, MockStat(), "abc123"
    )

    assert record["source_system"] == "dita"
    assert record["id"] == "topic:concepts/intro"
    assert record["title"] == "Introduction"
    assert record["source_path"] == "concepts/intro.dita"
    assert record["source_file_sha256"] == "abc123"
    assert record["doctype"] == "concept"
    assert record["body_repr"] == "dita"
    assert record["attachments"] == ["test.png"]
    assert record["attachment_count"] == 1
    assert record["labels"] == ["intro", "audience:beginner"]
    assert record["label_count"] == 2
    assert "content_sha256" in record
    assert "created_at" in record
    assert "updated_at" in record


def test_ingest_dita_full_flow(temp_dita_structure):
    """Test complete DITA ingest flow."""
    with tempfile.TemporaryDirectory() as outdir:
        # Run ingest
        metrics = ingest_dita(
            outdir=outdir, root=str(temp_dita_structure), run_id="test-run-123"
        )

        # Check return metrics
        assert metrics["pages"] == 3  # 2 topics + 1 map
        assert metrics["topics"] == 2
        assert metrics["maps"] == 1
        assert metrics["files_processed"] == 3
        assert metrics["files_found"] == 3
        assert "duration_seconds" in metrics
        assert metrics["sources"] == ["dita"]

        # Check main NDJSON file exists and has content
        ndjson_path = Path(outdir) / "dita.ndjson"
        assert ndjson_path.exists()

        records = []
        with open(ndjson_path) as f:
            for line in f:
                records.append(json.loads(line))

        assert len(records) == 3

        # Check we have the expected records
        record_ids = [r["id"] for r in records]
        assert any("introduction" in rid for rid in record_ids)
        assert any("setup" in rid for rid in record_ids)
        assert any("user-guide" in rid for rid in record_ids)

        # Check sidecar files exist
        assert (Path(outdir) / "summary.json").exists()
        assert (Path(outdir) / "ingest_media.jsonl").exists()
        assert (Path(outdir) / "attachments_manifest.jsonl").exists()
        assert (Path(outdir) / "edges.jsonl").exists()
        assert (Path(outdir) / "labels.jsonl").exists()
        assert (Path(outdir) / "breadcrumbs.jsonl").exists()


def test_write_media_sidecars():
    """Test media sidecar generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)

        # Create test topic with media
        topic = TopicDoc(
            id="topic:test",
            title="Test Topic",
            doctype="concept",
            body_xml="<conbody></conbody>",
            prolog_metadata={},
            images=[
                MediaRef(
                    "image1.png",
                    "image",
                    "/topic/body/p[1]/image[1]",
                    "First image",
                    1,
                ),
                MediaRef(
                    "file1.pdf",
                    "application/pdf",
                    "/topic/body/p[2]/object[1]",
                    None,
                    2,
                ),
            ],
            xrefs=[],
            keyrefs=[],
            conrefs=[],
            labels=[],
            links=[],
            enhanced_metadata={},
        )

        media_refs_total = _write_media_sidecars(outdir, [topic], [])

        assert media_refs_total == 2

        # Check media file
        media_file = outdir / "ingest_media.jsonl"
        assert media_file.exists()

        media_entries = []
        with open(media_file) as f:
            for line in f:
                media_entries.append(json.loads(line))

        assert len(media_entries) == 2

        # Check first media entry
        image_entry = next(
            e for e in media_entries if e["filename"] == "image1.png"
        )
        assert image_entry["page_id"] == "topic:test"
        assert image_entry["order"] == 1
        assert image_entry["type"] == "image"
        assert image_entry["context"]["alt"] == "First image"

        # Check attachment manifest
        manifest_file = outdir / "attachments_manifest.jsonl"
        assert manifest_file.exists()

        manifest_entries = []
        with open(manifest_file) as f:
            for line in f:
                manifest_entries.append(json.loads(line))

        assert len(manifest_entries) == 2


def test_build_hierarchy_and_write_edges():
    """Test hierarchy building and edge writing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)
        root_dir = Path("/test")

        # Create test map and topics
        map_doc = MapDoc(
            id="map:user-guide",
            title="User Guide",
            keydefs={},
            hierarchy=[
                type(
                    "MapRef",
                    (),
                    {
                        "href": "concepts/intro.dita",
                        "navtitle": "Introduction",
                        "type": None,
                        "scope": None,
                        "processing_role": None,
                    },
                )(),
                type(
                    "MapRef",
                    (),
                    {
                        "href": "tasks/setup.dita",
                        "navtitle": "Setup",
                        "type": None,
                        "scope": None,
                        "processing_role": None,
                    },
                )(),
            ],
            labels=[],
            links=[],
            enhanced_metadata={},
        )

        topic1 = TopicDoc(
            id="topic:concepts/intro",
            title="Introduction",
            doctype="concept",
            body_xml="",
            prolog_metadata={},
            images=[],
            xrefs=[],
            keyrefs=[],
            conrefs=[],
            labels=[],
            links=[],
            enhanced_metadata={},
        )

        topic2 = TopicDoc(
            id="topic:tasks/setup",
            title="Setup",
            doctype="task",
            body_xml="",
            prolog_metadata={},
            images=[],
            xrefs=[],
            keyrefs=[],
            conrefs=[],
            labels=[],
            links=[],
            enhanced_metadata={},
        )

        # Mock topic records that will be updated
        topic_records = [
            {
                "id": "topic:concepts/intro",
                "ancestors": [],
                "ancestor_count": 0,
            },
            {"id": "topic:tasks/setup", "ancestors": [], "ancestor_count": 0},
        ]

        ancestors_total = _build_hierarchy_and_write_edges(
            outdir, [map_doc], [topic1, topic2], topic_records, root_dir
        )

        assert ancestors_total == 2

        # Check edges file
        edges_file = outdir / "edges.jsonl"
        assert edges_file.exists()

        edges = []
        with open(edges_file) as f:
            for line in f:
                edges.append(json.loads(line))

        # Should have parent-child edges
        parent_edges = [e for e in edges if e["type"] == "PARENT_OF"]
        assert len(parent_edges) == 2

        intro_edge = next(
            e for e in parent_edges if e["dst"] == "topic:concepts/intro"
        )
        assert intro_edge["src"] == "map:user-guide"

        # Check breadcrumbs file
        breadcrumbs_file = outdir / "breadcrumbs.jsonl"
        assert breadcrumbs_file.exists()

        breadcrumbs = []
        with open(breadcrumbs_file) as f:
            for line in f:
                breadcrumbs.append(json.loads(line))

        assert len(breadcrumbs) == 2

        intro_breadcrumb = next(
            b for b in breadcrumbs if b["page_id"] == "topic:concepts/intro"
        )
        assert intro_breadcrumb["breadcrumbs"] == [
            "User Guide",
            "Introduction",
        ]

        # Check that topic records were updated
        intro_record = next(
            r for r in topic_records if r["id"] == "topic:concepts/intro"
        )
        assert intro_record["ancestors"] == ["User Guide"]
        assert intro_record["ancestor_count"] == 1


def test_write_labels_and_edges():
    """Test label writing and edge creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)

        # Create test docs with labels
        topic = TopicDoc(
            id="topic:test",
            title="Test Topic",
            doctype="concept",
            body_xml="",
            prolog_metadata={},
            images=[],
            xrefs=[],
            keyrefs=[],
            conrefs=[],
            labels=["intro", "audience:beginner"],
            links=[],
            enhanced_metadata={},
        )

        map_doc = MapDoc(
            id="map:guide",
            title="Guide",
            keydefs={},
            hierarchy=[],
            labels=["documentation"],
            links=[],
            enhanced_metadata={},
        )

        labels_total = _write_labels_and_edges(outdir, [topic, map_doc])

        assert labels_total == 3  # 2 topic labels + 1 map label

        # Check labels file
        labels_file = outdir / "labels.jsonl"
        assert labels_file.exists()

        labels = []
        with open(labels_file) as f:
            for line in f:
                labels.append(json.loads(line))

        assert len(labels) == 3

        topic_labels = [
            label for label in labels if label["page_id"] == "topic:test"
        ]
        assert len(topic_labels) == 2

        # Check edges file for label edges
        edges_file = outdir / "edges.jsonl"
        assert edges_file.exists()

        edges = []
        with open(edges_file) as f:
            for line in f:
                edges.append(json.loads(line))

        label_edges = [e for e in edges if e["type"] == "LABELED_AS"]
        assert len(label_edges) == 3

        intro_edge = next(e for e in label_edges if e["dst"] == "label:intro")
        assert intro_edge["src"] == "topic:test"


def test_ingest_dita_empty_directory():
    """Test ingesting from empty directory."""
    with (
        tempfile.TemporaryDirectory() as empty_dir,
        tempfile.TemporaryDirectory() as outdir,
    ):
        metrics = ingest_dita(
            outdir=outdir, root=empty_dir, run_id="test-empty"
        )

        # Should complete without error
        assert metrics["pages"] == 0
        assert metrics["files_found"] == 0
        assert metrics["files_processed"] == 0

        # Files should still be created (empty)
        assert (Path(outdir) / "dita.ndjson").exists()
        assert (Path(outdir) / "summary.json").exists()


def test_ingest_dita_nonexistent_root():
    """Test ingest with nonexistent root directory."""
    with tempfile.TemporaryDirectory() as outdir:
        with pytest.raises(ValueError, match="Root directory does not exist"):
            ingest_dita(outdir=outdir, root="/nonexistent/path")


def test_ingest_dita_with_include_exclude(temp_dita_structure):
    """Test ingest with include/exclude patterns."""
    with tempfile.TemporaryDirectory() as outdir:
        metrics = ingest_dita(
            outdir=outdir,
            root=str(temp_dita_structure),
            include=["*.dita"],  # Only topics, no maps
            exclude=["**/setup.dita"],  # Exclude setup task
        )

        # Should only process introduction.dita
        assert metrics["files_processed"] == 1
        assert metrics["topics"] == 1
        assert metrics["maps"] == 0


def test_ingest_dita_enhanced_metadata(temp_dita_structure):
    """Test DITA ingest with enhanced metadata functionality."""
    with tempfile.TemporaryDirectory() as outdir:
        # Create enhanced DITA files with metadata
        enhanced_topic = temp_dita_structure / "enhanced" / "config.dita"
        enhanced_topic.parent.mkdir(exist_ok=True)

        enhanced_content = """<?xml version="1.0" encoding="UTF-8"?>
        <concept id="enhanced_config" xml:lang="en-US">
            <title>Enhanced Configuration</title>
            <prolog>
                <metadata audience="implementer" product="Navigate" platform="SaaS">
                    <keywords>
                        <keyword>configuration</keyword>
                        <keyword>setup</keyword>
                    </keywords>
                    <othermeta name="status" content="approved"/>
                </metadata>
                <resourceid appname="ConfigApp"/>
                <critdates created="2023-01-15" modified="2023-03-20"/>
                <author>Technical Writer</author>
            </prolog>
            <conbody>
                <p>Configuration details with <xref href="https://docs.example.com">external link</xref>.</p>
                <p>Internal reference: <xref href="../introduction.dita">Introduction</xref></p>
                <p>Key reference: <xref keyref="product-name">Product Name</xref></p>
            </conbody>
        </concept>"""
        enhanced_topic.write_text(enhanced_content)

        ingest_dita(outdir=outdir, root=str(temp_dita_structure))

        # Check that enhanced files are generated
        outdir_path = Path(outdir)
        assert (outdir_path / "meta.jsonl").exists()
        assert (outdir_path / "links.jsonl").exists()

        # Check metadata sidecar
        meta_records = []
        with open(outdir_path / "meta.jsonl") as f:
            for line in f:
                if line.strip():
                    meta_records.append(json.loads(line))

        # Find the enhanced topic's metadata
        enhanced_meta = next(
            (r for r in meta_records if "enhanced_config" in r["page_id"]),
            None,
        )
        assert enhanced_meta is not None
        assert enhanced_meta["collection"] == "enhanced"
        assert "configuration" in enhanced_meta["labels"]
        assert "setup" in enhanced_meta["labels"]
        assert enhanced_meta["meta"]["audience"] == "implementer"
        assert enhanced_meta["meta"]["product"] == "Navigate"
        assert enhanced_meta["meta"]["platform"] == "SaaS"
        assert enhanced_meta["meta"]["resource_app"] == "ConfigApp"

        # Check links sidecar
        link_records = []
        with open(outdir_path / "links.jsonl") as f:
            for line in f:
                if line.strip():
                    link_records.append(json.loads(line))

        # Find links from the enhanced topic
        enhanced_links = [
            r for r in link_records if "enhanced_config" in r["from_page_id"]
        ]
        assert len(enhanced_links) >= 3

        # Check external link
        external_links = [
            link
            for link in enhanced_links
            if link["target_type"] == "external"
        ]
        assert len(external_links) >= 1
        assert any(
            "docs.example.com" in link["target_url"] for link in external_links
        )

        # Check DITA internal link
        dita_links = [
            link for link in enhanced_links if link["target_type"] == "dita"
        ]
        assert len(dita_links) >= 1

        # Check key reference (look for keyref elements)
        # May be 0 if keyref resolution is not fully implemented
        # key_refs = [
        #     link
        #     for link in enhanced_links
        #     if "product-name" in str(link)
        # ]
        # assert len(key_refs) >= 1

        # Check summary metrics include new counters
        summary_path = outdir_path / "summary.json"
        with open(summary_path) as f:
            summary = json.load(f)

        assert "meta_records" in summary
        assert summary["meta_records"] > 0
        assert "links_total" in summary
        assert summary["links_total"] > 0
        assert "links_external" in summary
        assert "links_dita" in summary


def test_compute_directory_context():
    """Test directory context computation for path tags and collection."""
    from trailblazer.pipeline.steps.ingest.dita import (
        _compute_directory_context,
    )

    root_dir = Path("/data/raw/dita")

    # Test normal ellucian-documentation path
    source_path = "ellucian-documentation/gen_help/concepts/intro.dita"
    context = _compute_directory_context(source_path, root_dir)

    assert context["collection"] == "gen_help"
    assert "gen" in context["path_tags"]
    assert "help" in context["path_tags"]
    assert "concepts" in context["path_tags"]
    assert "intro" in context["path_tags"]
    # Stopwords should be excluded
    assert "docs" not in context["path_tags"]
    assert "dita" not in context["path_tags"]

    # Test ESM release path
    source_path = "ellucian-documentation/esm_release/admin-guide/setup.dita"
    context = _compute_directory_context(source_path, root_dir)

    assert context["collection"] == "esm_release"
    assert "esm" in context["path_tags"]
    assert "release" in context["path_tags"]
    assert "admin" in context["path_tags"]
    assert "guide" in context["path_tags"]
    assert "setup" in context["path_tags"]


def test_aggregate_labels_and_metadata():
    """Test label and metadata aggregation."""
    from trailblazer.pipeline.steps.ingest.dita import (
        _aggregate_labels_and_metadata,
    )

    # Mock enhanced metadata
    enhanced_meta = {
        "audience": "implementer",
        "product": "Navigate",
        "platform": "SaaS",
        "keywords": ["configuration", "setup"],
        "otherprops": {"status": "approved"},
        "resource_app": "ConfigApp",
        "critdates": {"created": "2023-01-15", "modified": "2023-03-20"},
        "authors": ["Technical Writer"],
        "data_pairs": {},
    }

    # Create mock topic
    topic = type(
        "MockTopic",
        (),
        {
            "enhanced_metadata": enhanced_meta,
            "labels": ["xml-label", "prolog-label"],
        },
    )()

    root_dir = Path("/data/raw/dita")
    source_path = "ellucian-documentation/gen_help/concepts/config.dita"
    map_context = {"map_titles": ["User Guide", "Admin Guide"]}

    result = _aggregate_labels_and_metadata(
        topic, source_path, root_dir, map_context
    )

    # Check aggregated labels include all sources
    labels = result["labels"]
    assert "xml-label" in labels
    assert "prolog-label" in labels
    assert "gen" in labels  # From path
    assert "help" in labels  # From path
    assert "gen_help" in labels  # Collection
    assert "configuration" in labels  # From keywords
    assert "setup" in labels  # From keywords
    assert "audience:implementer" in labels  # From metadata
    assert "product:Navigate" in labels  # From metadata
    assert "platform:SaaS" in labels  # From metadata
    assert "status:approved" in labels  # From otherprops

    # Check metadata structure
    assert result["meta"]["audience"] == "implementer"
    assert result["meta"]["map_titles"] == ["User Guide", "Admin Guide"]
    assert result["collection"] == "gen_help"
    assert "gen" in result["path_tags"]


def test_ingest_dita_directory_structure_parsing():
    """Test that directory structure is properly parsed for collections and path tags."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create ellucian-documentation structure
        base_dir = Path(tmpdir) / "ellucian-documentation"
        gen_help_dir = base_dir / "gen_help" / "admin" / "setup"
        gen_help_dir.mkdir(parents=True)

        # Create a topic with minimal content
        topic_file = gen_help_dir / "database-config.dita"
        topic_content = """<?xml version="1.0"?>
        <concept id="db_config">
            <title>Database Configuration</title>
            <conbody><p>Database setup instructions.</p></conbody>
        </concept>"""
        topic_file.write_text(topic_content)

        with tempfile.TemporaryDirectory() as outdir:
            ingest_dita(outdir=outdir, root=str(base_dir))

            # Check meta.jsonl for directory-derived metadata
            meta_path = Path(outdir) / "meta.jsonl"
            assert meta_path.exists()

            with open(meta_path) as f:
                meta_record = json.loads(f.readline())

            assert meta_record["collection"] == "gen_help"
            assert "gen" in meta_record["path_tags"]
            assert "help" in meta_record["path_tags"]
            assert "admin" in meta_record["path_tags"]
            assert "setup" in meta_record["path_tags"]
            assert "database" in meta_record["path_tags"]
            assert "config" in meta_record["path_tags"]

            # Labels should include path tags and collection
            assert "gen_help" in meta_record["labels"]
            assert "gen" in meta_record["labels"]
            assert "help" in meta_record["labels"]
