from trailblazer.core.artifacts import new_run_id


def test_run_id_shape():
    rid = new_run_id()
    assert "_" in rid and len(rid.split("_")[-1]) == 4
