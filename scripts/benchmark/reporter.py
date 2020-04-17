"""Reporting module that can write results to a CSV file."""
import csv
import sys
import pathlib
import dataclasses

from typing import List, Iterable, Callable, TypeVar, Any

from . import evaluate
from . import gitutils
from . import run


@dataclasses.dataclass(frozen=True)
class FileMergeMetainfo:
    merge_commit: str
    merge_blob: str
    merge_filepath: str
    base_commit: str
    base_blob: str
    base_filepath: str
    left_commit: str
    left_blob: str
    left_filepath: str
    right_commit: str
    right_blob: str
    right_filepath: str

    @classmethod
    def field_names(cls):
        return [f.name for f in dataclasses.fields(cls)]


T = TypeVar("T")


def write_results(results: Iterable[evaluate.MergeEvaluation], dst: str) -> None:
    _write_csv(
        headers=list(evaluate.MergeEvaluation._fields),
        body=[[str(v) for v in res] for res in results],
        dst=dst,
    )


def read_results(results_path: pathlib.Path) -> List[evaluate.MergeEvaluation]:
    return _read_csv(
        expected_headers=list(evaluate.MergeEvaluation._fields),
        wrapper_class=evaluate.MergeEvaluation,
        csv_file=results_path,
    )


def read_git_merge_results(csv_file: pathlib.Path) -> List[run.GitMergeResult]:
    return _read_csv(
        expected_headers=list(run.GitMergeResult._fields),
        wrapper_class=run.GitMergeResult,
        csv_file=csv_file,
    )


def read_file_merge_metainfo(csv_file: pathlib.Path) -> List[FileMergeMetainfo]:
    return _read_csv(
        expected_headers=list(FileMergeMetainfo.field_names()),
        wrapper_class=FileMergeMetainfo,
        csv_file=csv_file,
    )


def write_file_merge_metainfo(file_merges: List[gitutils.FileMerge], dst: str) -> None:
    metainfos = map(_file_merge_to_metainfo, file_merges)
    _write_csv(
        headers=FileMergeMetainfo.field_names(),
        body=[dataclasses.astuple(meta) for meta in metainfos],
        dst=dst,
    )


def write_git_merge_results(
    merge_results: Iterable[run.GitMergeResult], dst: str
) -> None:
    _write_csv(
        headers=list(run.GitMergeResult._fields),
        body=[[str(v) for v in res] for res in merge_results],
        dst=dst,
    )


def write_runtime_results(
    runtime_results: Iterable[run.RuntimeResult], dst: str
) -> None:
    _write_csv(
        headers=list(run.RuntimeResult._fields),
        body=[[str(v) for v in res] for res in runtime_results],
        dst=dst,
    )


def _file_merge_to_metainfo(file_merge: gitutils.FileMerge) -> FileMergeMetainfo:
    ms = file_merge.from_merge_scenario

    base_blob = file_merge.base.hexsha if file_merge.base else ""
    base_filepath = file_merge.base.path if file_merge.base else ""

    return FileMergeMetainfo(
        merge_commit=ms.result.hexsha,
        base_commit=ms.base.hexsha,
        left_commit=ms.left.hexsha,
        right_commit=ms.right.hexsha,
        merge_blob=file_merge.result.hexsha,
        merge_filepath=str(file_merge.result.path),
        base_blob=base_blob,
        base_filepath=base_filepath,
        left_blob=file_merge.left.hexsha,
        left_filepath=str(file_merge.left.path),
        right_blob=file_merge.right.hexsha,
        right_filepath=str(file_merge.right.path),
    )


def _read_csv(
    expected_headers: List[str], wrapper_class: Callable[..., T], csv_file: pathlib.Path
) -> Callable[..., T]:
    with open(str(csv_file), mode="r") as file:
        reader = csv.reader(file, dialect=_IgnoreWhitespaceDialect())
        headers = list(next(reader))

        if headers != expected_headers:
            raise ValueError(
                "provided CSV file has wrong headers, expected "
                f"{expected_headers}, got {headers}"
            )

        return [wrapper_class(*[_parse_value(v) for v in line]) for line in reader]


def _write_csv(headers: List[str], body: List[List[str]], dst: str):
    sorted_body = sorted(body)
    formatted_content = _format_for_csv([headers, *sorted_body])

    with open(dst, mode="w", encoding=sys.getdefaultencoding()) as file:
        writer = csv.writer(file, delimiter=",")
        writer.writerows(formatted_content)


def _parse_value(v: str):
    if "/" in v:  # this is a path
        return pathlib.Path(v)

    for conv_func in [int, float]:
        try:
            return conv_func(v)
        except ValueError:
            pass
    return v


def _format_for_csv(results: List[List[str]]) -> List[List[str]]:
    column_widths = [largest + 1 for largest in _largest_cells(results)]
    return [
        [cell.rjust(column_widths[i]) for i, cell in enumerate(row)] for row in results
    ]


def _largest_cells(rows):
    """Return a list with the widths of the largest cell of each column."""
    transpose = list(zip(*rows))
    widths = map(lambda row: map(len, row), transpose)
    return list(map(max, widths))


class _IgnoreWhitespaceDialect(csv.unix_dialect):
    skipinitialspace = True
