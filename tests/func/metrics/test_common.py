import logging

import pytest

from dvc.exceptions import DvcException
from tests.func.metrics.utils import _write_json


def _metrics_diff(dvc, filename, revision):
    dvc.metrics.diff(targets=[filename], a_rev=revision)


def _plots_diff(dvc, filename, revision):
    dvc.plots.diff(targets=[filename], revs=[revision])


@pytest.mark.parametrize(
    "diff_fun, metric_value",
    ((_metrics_diff, {"m": 1}), (_plots_diff, [{"m": 1}, {"m": 2}])),
)
def test_diff_no_file_on_target_rev(
    tmp_dir, scm, dvc, caplog, diff_fun, metric_value
):
    with tmp_dir.branch("new_branch", new=True):
        _write_json(tmp_dir, metric_value, "metric.json")

        with caplog.at_level(logging.WARNING, "dvc"):
            diff_fun(dvc, "metric.json", "master")

    assert "'metric.json' was not found at: 'master'." in caplog.text


@pytest.mark.parametrize(
    "show_provider, malformed_metric",
    [
        (lambda repo: repo.plots, '[{"val":2}, {"val":3]'),
        (lambda repo: repo.metrics, '{"val":2'),
    ],
)
def test_show_bad_data_format(
    tmp_dir, dvc, caplog, show_provider, malformed_metric
):
    tmp_dir.dvc_gen("file.json", malformed_metric)

    with pytest.raises(DvcException):
        show_provider(dvc).show(targets=["file.json"])
