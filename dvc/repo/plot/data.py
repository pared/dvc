import csv
import io
import json
import logging
import os
from collections import OrderedDict
from copy import copy

from funcy import first, last, cached_property
from ruamel import yaml

from dvc.exceptions import DvcException, PathMissingError


logger = logging.getLogger(__name__)

WORKSPACE_REVISION_NAME = "workspace"


class PlotMetricTypeError(DvcException):
    def __init__(self, file):
        super().__init__(
            "'{}' - file type error\n"
            "Only json, yaml, csv and tsv types are supported.".format(file)
        )


class PlotDataStructureError(DvcException):
    def __init__(self):
        super().__init__("Plot data extraction failed.")


class JsonParsingError(DvcException):
    def __init__(self, file):
        super().__init__(
            "Failed to infer data structure from '{}'. Did you forget "
            "to specify jsonpath?".format(file)
        )


class NoMetricOnRevisionError(DvcException):
    def __init__(self, path, revision):
        self.path = path
        self.revision = revision
        super().__init__(
            "Could not find '{}' on revision " "'{}'".format(path, revision)
        )


class NoMetricInHistoryError(DvcException):
    def __init__(self, path, revisions):
        super().__init__(
            "Could not find '{}' on any of the revisions "
            "'{}'".format(path, ", ".join(revisions))
        )


def plot_data(filename, revision, content):
    _, extension = os.path.splitext(filename.lower())
    if extension == ".json":
        return JSONPlotData(filename, revision, content)
    elif extension == ".csv":
        return CSVPlotData(filename, revision, content)
    elif extension == ".tsv":
        return CSVPlotData(filename, revision, content, delimiter="\t")
    elif extension == ".yaml":
        return YAMLPLotData(filename, revision, content)
    raise PlotMetricTypeError(filename)


def _filter_fields(data_points, fieldnames=None, fields=None, **kwargs):
    if not fields:
        return data_points, fieldnames
    assert isinstance(fields, set)

    new_data = []
    for data_point in data_points:
        new_dp = copy(data_point)

        keys = set(data_point.keys())
        if keys & fields != fields:
            raise DvcException(
                "Could not find some of provided fields: "
                "'{}' in '{}'.".format(", ".join(fields), ", ".join(keys))
            )

        to_del = keys - fields
        for key in to_del:
            del new_dp[key]
            if fieldnames and key in fieldnames:
                fieldnames.remove(key)
        new_data.append(new_dp)
    return new_data, fieldnames


def _transform_to_default_data(
    data_points, fieldnames=None, default_plot=False, **kwargs
):
    if not default_plot:
        return data_points, fieldnames

    new_data = []
    if fieldnames:
        y = last(fieldnames)
    else:
        y = last(list(first(data_points).keys()))

    for index, data_point in enumerate(data_points):
        new_data.append({"x": index, "y": data_point[y]})
    return new_data, ["x", "y"]


def _apply_path(data, fieldnames=None, path=None, **kwargs):
    if not path or not isinstance(data, dict):
        return data, fieldnames

    import jsonpath_ng

    found = jsonpath_ng.parse(path).find(data)
    first_datum = first(found)
    if (
        len(found) == 1
        and isinstance(first_datum.value, list)
        and isinstance(first(first_datum.value), dict)
    ):
        data_points = first_datum.value
        fieldnames = list(first(data_points).keys())
    elif len(first_datum.path.fields) == 1:
        field_name = first(first_datum.path.fields)
        fieldnames = [field_name]
        data_points = [{field_name: datum.value} for datum in found]
    else:
        raise PlotDataStructureError()

    if not isinstance(data_points, list) or not (
        isinstance(first(data_points), dict)
    ):
        raise PlotDataStructureError()

    return data_points, fieldnames


def _lists(dictionary):
    for key, value in dictionary.items():
        if isinstance(value, dict):
            yield from (_lists(value))
        elif isinstance(value, list):
            yield value


def _find_data(data, fieldnames=None, fields=None, **kwargs):
    if not fields or not isinstance(data, dict):
        return data, fieldnames

    assert isinstance(fields, set)

    for l in _lists(data):
        if all([isinstance(dp, dict) for dp in l]):
            if set(first(l).keys()) & fields == fields:
                if fieldnames:
                    return l, [f for f in fieldnames if f in fields]
                return l, None
    raise PlotDataStructureError()


class PlotData:
    def __init__(self, filename, revision, content, **kwargs):
        self.filename = filename
        self.revision = revision
        self.content = content
        self.fieldnames = None

    @property
    def raw(self):
        raise NotImplementedError

    def _processors(self):
        return [_filter_fields, _transform_to_default_data]

    def to_datapoints(self, **kwargs):
        data = self.raw
        fieldnames = self.fieldnames

        for data_proc in self._processors():
            data, fieldnames = data_proc(data, fieldnames, **kwargs)

        for data_point in data:
            data_point["rev"] = self.revision
        return data


class JSONPlotData(PlotData):
    @cached_property
    def raw(self):
        return json.loads(self.content, object_pairs_hook=OrderedDict)

    def _processors(self):
        parent_processors = super(JSONPlotData, self)._processors()
        return [_apply_path, _find_data] + parent_processors


class CSVPlotData(PlotData):
    def __init__(self, filename, revision, content, delimiter=","):
        super(CSVPlotData, self).__init__(filename, revision, content)
        self.delimiter = delimiter

    @cached_property
    def raw(self):
        first_row = first(csv.reader(io.StringIO(self.content)))

        if len(first_row) == 1:
            reader = csv.DictReader(
                io.StringIO(self.content),
                delimiter=self.delimiter,
                fieldnames=["value"],
            )
        else:
            reader = csv.DictReader(
                io.StringIO(self.content),
                skipinitialspace=True,
                delimiter=self.delimiter,
            )

        self.fieldnames = reader.fieldnames
        return [row for row in reader]


class YAMLPLotData(PlotData):
    @cached_property
    def raw(self):
        return yaml.parse(io.StringIO(self.content))


def _load_from_revision(repo, datafile, revision):
    if revision is WORKSPACE_REVISION_NAME:

        def open_datafile():
            return repo.tree.open(datafile, "r")

    else:

        def open_datafile():
            from dvc import api

            return api.open(datafile, repo.root_dir, revision)

    try:
        with open_datafile() as fobj:
            datafile_content = fobj.read()

    except (FileNotFoundError, PathMissingError):
        raise NoMetricOnRevisionError(datafile, revision)

    return plot_data(datafile, revision, datafile_content)


def _load_from_revisions(repo, datafile, revisions):
    data = []
    exceptions = []

    for rev in revisions:
        try:
            data.append(_load_from_revision(repo, datafile, rev))
        except NoMetricOnRevisionError as e:
            exceptions.append(e)
        except PlotMetricTypeError:
            raise
        except Exception:
            logger.error("Failed to parse '{}' at '{}'.".format(datafile, rev))
            raise

    if not data and exceptions:
        raise NoMetricInHistoryError(datafile, revisions)
    else:
        for e in exceptions:
            logger.warning(
                "File '{}' was not found at: '{}'. It will not be "
                "plotted.".format(e.path, e.revision)
            )
    return data