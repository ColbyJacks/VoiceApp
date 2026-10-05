import pytest

from voiceapp_studio.cli import main
from voiceapp_studio.project import Project, TrainingConfig


def test_create_and_reload(tmp_path):
    project = Project.create(tmp_path / "alice", TrainingConfig(name="alice", epochs=50))
    for sub in Project.SUBDIRS:
        assert (project.root / sub).is_dir()
    assert project.load_config().epochs == 50


def test_refuses_to_overwrite(tmp_path):
    Project.create(tmp_path, TrainingConfig(name="a"))
    with pytest.raises(FileExistsError):
        Project.create(tmp_path, TrainingConfig(name="a"))


@pytest.mark.parametrize("cfg", [TrainingConfig(name="a/b"), TrainingConfig(name="a", sample_rate=44100)])
def test_validation(cfg):
    with pytest.raises(ValueError):
        cfg.validate()


def test_cli_new_and_unimplemented_step(tmp_path, capsys):
    assert main(["new", str(tmp_path / "p"), "--name", "p"]) == 0
    assert main(["train", str(tmp_path / "p")]) == 2
    assert main(["new", str(tmp_path / "q"), "--name", "q", "--sample-rate", "1"]) == 1
