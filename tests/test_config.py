import pytest

from captionflow_harvester.config import Config


def test_config_rejects_bad_worker_count():
    with pytest.raises(ValueError):
        Config(worker_count=0).validate()


def test_target_prospects_is_goal_not_validation_cap():
    cfg = Config(target_prospects_per_run=500)
    cfg.validate()
    assert cfg.target_prospects_per_run == 500
