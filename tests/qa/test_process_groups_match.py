"""Test process groups matching with hyphen/stem variants."""

# pytest is used for test discovery and running

from trailblazer.qa.expect import contains_any


class TestProcessGroupsMatch:
    """Test that process groups match various text formats."""

    def test_capability_driven_variants(self):
        """Test capability-driven variants match."""
        text = "This is a capability-driven approach to development"
        terms = ["capability-driven", "capability led", "capability-led"]

        assert contains_any(text, terms) is True

    def test_capability_driven_hyphen_variants(self):
        """Test capability-driven hyphen variants match."""
        text = "We use a capability driven methodology"
        terms = ["capability-driven", "capability driven", "capability-led"]

        assert contains_any(text, terms) is True

    def test_testing_strategy_variants(self):
        """Test testing strategy variants match."""
        text = "Our testing strategy includes automation"
        terms = ["testing strategy", "test strategy", "qa strategy"]

        assert contains_any(text, terms) is True

    def test_continuous_testing_stemming(self):
        """Test continuous testing with stemming."""
        text = "We implement continuous testing in our pipeline"
        terms = ["continuous testing", "test automation", "shift-left"]

        assert contains_any(text, terms) is True

    def test_data_migration_variants(self):
        """Test data migration variants match."""
        text = "The data migration plan includes ETL processes"
        terms = ["data migration", "cutover data load", "dm strategy"]

        assert contains_any(text, terms) is True

    def test_integration_patterns_variants(self):
        """Test integration patterns variants match."""
        text = "We follow integration patterns for APIs"
        terms = ["integration patterns", "ethos", "api pattern"]

        assert contains_any(text, terms) is True

    def test_governance_variants(self):
        """Test governance variants match."""
        text = "The governance framework uses RACI"
        terms = ["governance", "raaci", "raci", "decision rights"]

        assert contains_any(text, terms) is True

    def test_sprint0_variants(self):
        """Test Sprint 0 variants match."""
        text = "Sprint 0 focuses on architecture alignment"
        terms = ["sprint 0", "architecture alignment", "aaw"]

        assert contains_any(text, terms) is True

    def test_deploy_cutover_variants(self):
        """Test deploy/cutover variants match."""
        text = "The deployment includes cutover procedures"
        terms = ["cutover", "go-live", "deployment", "hypercare"]

        assert contains_any(text, terms) is True

    def test_configuration_variants(self):
        """Test configuration variants match."""
        text = "System configuration requires setup steps"
        terms = ["configure", "configuration", "setup", "parameterization"]

        assert contains_any(text, terms) is True

    def test_no_match(self):
        """Test that unrelated terms don't match."""
        text = "This is about database performance optimization"
        terms = ["capability-driven", "testing strategy", "data migration"]

        assert contains_any(text, terms) is False

    def test_stopwords_filtered(self):
        """Test that stopwords are filtered out."""
        text = "We have experience with solution development"
        terms = ["experience", "solution", "issue"]

        assert contains_any(text, terms) is False

    def test_stemming_ing_suffix(self):
        """Test stemming of -ing suffix."""
        text = "We are planning the project"
        terms = ["plan", "planning"]

        assert contains_any(text, terms) is True

    def test_stemming_ed_suffix(self):
        """Test stemming of -ed suffix."""
        text = "The project was planned carefully"
        terms = ["plan", "planned"]

        assert contains_any(text, terms) is True
