import pytest

from codejudge.stages import default_stages


def test_subset_still_runs_integrity_and_build():
    names = [stage.name for stage in default_stages(["security"])]
    assert names == ["integrity", "build", "security"]


def test_unknown_stage_is_rejected():
    with pytest.raises(ValueError, match="unknown stage"):
        default_stages(["nope"])
