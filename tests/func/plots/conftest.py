import os

import pytest

from dvc.repo.plots.template import DefaultLinearTemplate


@pytest.fixture()
def custom_template(tmp_dir, dvc):
    template = tmp_dir / "custom_template.json"
    DefaultLinearTemplate(path=os.fspath(template)).dump()
    return template
