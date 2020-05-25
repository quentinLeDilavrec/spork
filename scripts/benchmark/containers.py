"""Containers for storing results of various kinds."""
import dataclasses
import collections
import pathlib
import git
import enum
import pathlib

from typing import Optional


@dataclasses.dataclass(frozen=True)
class MergeScenario:
    expected: git.Commit
    base: git.Commit
    left: git.Commit
    right: git.Commit

    @staticmethod
    def from_metainfo(
        repo: git.Repo, metainfo: "FileMergeMetainfo"
    ) -> "MergeScenario":
        return MergeScenario(
            expected=repo.commit(metainfo.merge_commit),
            base=repo.commit(metainfo.base_commit),
            left=repo.commit(metainfo.left_commit),
            right=repo.commit(metainfo.right_commit),
        )

    @staticmethod
    def from_serializable(
        repo: git.Repo, serializable: "SerializableMergeScenario"
    ) -> "MergeScenario":
        return MergeScenario(
            expected=repo.commit(serializable.expected),
            base=repo.commit(serializable.base),
            left=repo.commit(serializable.left),
            right=repo.commit(serializable.right),
        )


@dataclasses.dataclass(frozen=True)
class SerializableMergeScenario:
    expected: str
    base: str
    left: str
    right: str

    @staticmethod
    def from_merge_scenario(ms: MergeScenario) -> "SerializableMergeScenario":
        return SerializableMergeScenario(
            expected=ms.expected.hexsha,
            base=ms.base.hexsha,
            left=ms.left.hexsha,
            right=ms.right.hexsha,
        )


@dataclasses.dataclass(frozen=True)
class FileMerge:
    expected: git.Blob
    base: Optional[git.Blob]
    left: git.Blob
    right: git.Blob
    from_merge_scenario: MergeScenario

    @staticmethod
    def from_metainfo(repo: git.Repo, metainfo) -> "FileMerge":
        ms = MergeScenario.from_metainfo(repo, metainfo)
        expected = ms.expected.tree[str(metainfo.expected_filepath)]
        base = (
            ms.base.tree[str(metainfo.base_filepath)]
            if metainfo.base_filepath
            else None
        )
        left = ms.left.tree[str(metainfo.left_filepath)]
        right = ms.right.tree[str(metainfo.right_filepath)]
        return FileMerge(
            expected=expected,
            base=base,
            left=left,
            right=right,
            from_merge_scenario=ms,
        )


@dataclasses.dataclass(frozen=True, order=True)
class FileMergeMetainfo:
    merge_commit: str
    expected_blob: str
    expected_filepath: str
    base_commit: str
    base_blob: str
    base_filepath: str
    left_commit: str
    left_blob: str
    left_filepath: str
    right_commit: str
    right_blob: str
    right_filepath: str

    @staticmethod
    def from_file_merge(file_merge: FileMerge) -> "FileMergeMetainfo":
        ms = file_merge.from_merge_scenario

        base_blob = file_merge.base.hexsha if file_merge.base else ""
        base_filepath = file_merge.base.path if file_merge.base else ""

        return FileMergeMetainfo(
            merge_commit=ms.expected.hexsha,
            base_commit=ms.base.hexsha,
            left_commit=ms.left.hexsha,
            right_commit=ms.right.hexsha,
            expected_blob=file_merge.expected.hexsha,
            expected_filepath=str(file_merge.expected.path),
            base_blob=base_blob,
            base_filepath=base_filepath,
            left_blob=file_merge.left.hexsha,
            left_filepath=str(file_merge.left.path),
            right_blob=file_merge.right.hexsha,
            right_filepath=str(file_merge.right.path),
        )


@dataclasses.dataclass(frozen=True, order=True)
class JavaBlobMetainfo:
    hexsha: str
    num_lines: int


@dataclasses.dataclass(frozen=True, order=True)
class MergeEvaluation:
    merge_dir: pathlib.Path
    merge_commit: str
    base_blob: str
    left_blob: str
    right_blob: str
    expected_blob: str
    replayed_blob: str
    merge_cmd: str
    outcome: str
    git_diff_size: int
    num_conflicts: int
    conflict_size: int
    runtime: float


class Revision(enum.Enum):
    BASE = enum.auto()
    LEFT = enum.auto()
    RIGHT = enum.auto()
    ACTUAL_MERGE = enum.auto()


class MergeOutcome:
    CONFLICT = "conflict"
    SUCCESS = "success"
    FAIL = "fail"


@dataclasses.dataclass(frozen=True)
class MergeResult:
    merge_dir: pathlib.Path
    merge_file: pathlib.Path
    base_file: pathlib.Path
    left_file: pathlib.Path
    right_file: pathlib.Path
    expected_file: pathlib.Path
    merge_cmd: str
    outcome: MergeOutcome
    runtime: int


@dataclasses.dataclass(frozen=True, order=True)
class GitMergeResult:
    merge_commit: str
    classfile_dir: str
    original_classfile_path: str
    merge_driver: str
    build_ok: bool
    merge_ok: bool
    eval_ok: bool


@dataclasses.dataclass(frozen=True, order=True)
class RuntimeResult:
    merge_commit: str
    base_blob: str
    left_blob: str
    right_blob: str
    runtime_ms: int
    merge_cmd: str


@dataclasses.dataclass(frozen=True, order=True)
class MergeEvaluationStatistics:
    project: str
    merge_cmd: str
    num_file_merges: int
    num_success: int
    num_conflict: int
    num_fail: int
    git_diff_avg_magn: int
    git_diff_avg_acc: int


@dataclasses.dataclass
class ExpectedClassfile:
    copy_abspath: pathlib.Path
    copy_basedir: pathlib.Path
    original_relpath: pathlib.Path


@dataclasses.dataclass
class ClassfilePair:
    expected: ExpectedClassfile
    replayed: pathlib.Path
