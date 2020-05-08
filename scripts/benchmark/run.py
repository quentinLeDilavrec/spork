import subprocess
import itertools
import os
import sys
import time
import pathlib
import dataclasses
import collections
import enum
import contextlib
import tempfile
import shutil
from typing import List, Generator, Iterable, Tuple

import git
import daiquiri

from . import gitutils
from . import fileutils
from . import containers as conts
from . import javautils

LOGGER = daiquiri.getLogger(__name__)


def run_file_merges(
    file_merge_dirs: List[pathlib.Path], merge_cmd: str
) -> Iterable[conts.MergeResult]:
    """Run the file merges in the provided directories and put the output in a
    file called `merge_cmd`.java.

    Args:
        file_merge_dirs: A list of directories with file merge scenarios. Each
            directory must contain Base.java, Left.java, Right.java and
            Expected.java
        merge_cmd: The merge command to execute. Will be called as
            `merge_cmd Left.java Base.java Right.java -o merge_cmd.java`.
    Returns:
        A generator that yields one conts.MergeResult per merge directory.
    """
    for merge_result, _ in _run_file_merges(file_merge_dirs, merge_cmd):
        yield merge_result


def _run_file_merges(
    file_merge_dirs: List[pathlib.Path], merge_cmd: str
) -> Iterable:
    sanitized_merge_cmd = pathlib.Path(merge_cmd).name.replace(" ", "_")
    for merge_dir in file_merge_dirs:
        filenames = [f.name for f in merge_dir.iterdir() if f.is_file()]

        def get_filename(prefix: str) -> str:
            matches = [name for name in filenames if name.startswith(prefix)]
            assert len(matches) == 1
            return matches[0]

        merge_file = merge_dir / f"{sanitized_merge_cmd}.java"
        base = merge_dir / get_filename("Base")
        left = merge_dir / get_filename("Left")
        right = merge_dir / get_filename("Right")
        expected = merge_dir / get_filename("Expected")

        assert base.is_file()
        assert left.is_file()
        assert right.is_file()
        assert expected.is_file()

        outcome, runtime, proc = _run_file_merge(
            merge_dir,
            merge_cmd,
            base=base,
            left=left,
            right=right,
            expected=expected,
            merge=merge_file,
        )
        yield conts.MergeResult(
            merge_dir=merge_dir,
            merge_file=merge_file,
            base_file=base,
            left_file=left,
            right_file=right,
            expected_file=expected,
            merge_cmd=sanitized_merge_cmd,
            outcome=outcome,
            runtime=runtime,
        ), proc


def _run_file_merge(
    scenario_dir, merge_cmd, base, left, right, expected, merge
):
    start = time.perf_counter()
    proc = subprocess.run(
        f"{merge_cmd} {left} {base} {right} -o {merge}".split(),
        capture_output=True,
    )
    runtime = time.perf_counter() - start

    if not merge.is_file():
        LOGGER.error(
            f"{merge_cmd} failed to produce a merge file on {scenario_dir.parent.name}/{scenario_dir.name}"
        )
        LOGGER.info(proc.stdout.decode(sys.getdefaultencoding()))
        LOGGER.info(proc.stderr.decode(sys.getdefaultencoding()))
        return conts.MergeOutcome.FAIL, runtime, proc
    elif proc.returncode != 0:
        LOGGER.warning(
            f"Merge conflict in {scenario_dir.parent.name}/{scenario_dir.name}"
        )
        return conts.MergeOutcome.CONFLICT, runtime, proc
    else:
        LOGGER.info(
            f"Successfully merged {scenario_dir.parent.name}/{scenario_dir.name}"
        )
        return conts.MergeOutcome.SUCCESS, runtime, proc


def run_git_merges(
    merge_scenarios: List[conts.MergeScenario],
    merge_drivers: List[str],
    repo: git.Repo,
    build: bool,
    evaluate: bool,
) -> Iterable[conts.GitMergeResult]:
    """Replay the provided merge scenarios using git-merge. Assumes that the
    merge scenarios belong to the provided repo. The merge drivers must be
    defined in the global .gitconfig file, https://github.com/kth/spork for
    details on that.

    Args:
        merge_scenarios: A list of merge scenarios.
        merge_drivers: A list of merge driver names to execute the merge with.
            Each driver must be defined in the global .gitconfig file.
        repo: The related repository.
        build: If True, try to build the project with Maven after merge.
        evaluate: Run the Java-specific bytecode evaluation.
    Returns:
        An iterable of merge results.
    """
    for ms in merge_scenarios:
        LOGGER.info(
            f"Replaying merge commit {ms.expected.hexsha}, "
            f"base: {ms.base.hexsha} left: {ms.left.hexsha} "
            f"right: {ms.right.hexsha}"
        )
        yield from run_git_merge(ms, merge_drivers, repo, build, evaluate)


def run_git_merge(
    merge_scenario: conts.MergeScenario,
    merge_drivers: List[str],
    repo: git.Repo,
    build: bool,
    evaluate: bool,
) -> conts.GitMergeResult:
    """Replay a single merge scenario. Assumes that the merge scenario belongs
    to the provided repo. The merge tool to use must be configured in
    .gitattributes and .gitconfig, see the README at
    https://github.com/kth/spork for details on that.

    Args:
        merge_scenario: A merge scenario.
        merge_drivers: One or more merge driver names. Each merge driver must
            be defined in the global .gitconfig file.
        repo: The related repository.
        build: If True, try to build the project with Maven after merge.
        evaluate: Run the Java bytecode evaluation. Implies build.
    Returns:
        An iterable of GitMergeResults, one for each driver
    """
    ms = merge_scenario  # alias for less verbosity
    expected_classfiles = tuple()

    with (
        tempfile.TemporaryDirectory() if evaluate else _nop_context()
    ) as ctx:
        if evaluate:
            with gitutils.saved_git_head(repo):
                (
                    expected_classfiles,
                    expected_compile_basedir,
                ) = _extract_expected_revision_classfiles(
                    repo, ms, pathlib.Path(ctx)
                )
                if not expected_classfiles:
                    LOGGER.warning(
                        "Found no expected classfiles for merge scenario "
                        f"{ms.expected.hexsha}, skipping ..."
                    )
                    return

        for merge_driver in merge_drivers:
            build_ok = False
            eval_ok = False
            num_equal_classfiles = 0

            with gitutils.merge_no_commit(
                repo,
                ms.left.hexsha,
                ms.right.hexsha,
                driver_config=(merge_driver, "*.java"),
            ) as merge_stat:
                merge_ok, _ = merge_stat
                _log_cond(
                    "Merge replay OK",
                    "Merge conflict or failure",
                    use_info=merge_ok,
                )

                if build or evaluate:
                    LOGGER.info("Building replayed revision")
                    build_ok = fileutils.mvn_compile(
                        workdir=repo.working_tree_dir
                    )
                    _log_cond(
                        "Replayed build OK",
                        "Replayed build failed",
                        use_info=build_ok,
                    )

                    if build_ok and evaluate:
                        num_equal_classfiles = javautils.compare_compiled_bytecode(
                            pathlib.Path(repo.working_tree_dir) / "target",
                            expected_classfiles,
                        )

            yield conts.GitMergeResult(
                merge_commit=ms.expected.hexsha,
                merge_driver=merge_driver,
                merge_ok=merge_ok,
                build_ok=build_ok,
                num_equal_classfiles=num_equal_classfiles,
                num_expected_classfiles=len(expected_classfiles),
                base_commit=ms.base.hexsha,
                left_commit=ms.left.hexsha,
                right_commit=ms.right.hexsha,
            )


def _extract_expected_revision_classfiles(
    repo: git.Repo, ms: conts.MergeScenario, tempdir: pathlib.Path
) -> Tuple[pathlib.Path]:
    gitutils.checkout_clean(repo, ms.expected.hexsha)
    LOGGER.info("Building expected revision")

    if not fileutils.mvn_compile(workdir=repo.working_tree_dir):
        raise RuntimeError(
            f"Failed to build expected revision {ms.expected.hexsha}"
        )

    LOGGER.info("Making temporary copy of expected build")
    expected_compile_basedir = tempdir / "target"
    shutil.copytree(
        pathlib.Path(repo.working_tree_dir) / "target",
        expected_compile_basedir,
    )

    sources = [
        repo.working_tree_dir / path
        for path in gitutils.extract_unmerged_files(repo, ms, file_ext=".java")
    ]
    LOGGER.info(f"Extracted unmerged files: {sources}")

    expected_classfiles = tuple(
        itertools.chain.from_iterable(
            javautils.locate_classfiles(src, basedir=expected_compile_basedir)
            for src in sources
        )
    )
    LOGGER.info(f"Extracted classfiles: {expected_classfiles}")

    for classfile in expected_classfiles:
        LOGGER.info(
            f"Removing duplicate checkcasts from expected revision of {classfile.name}"
        )
        javautils.remove_duplicate_checkcasts(classfile)

    return expected_classfiles, expected_compile_basedir


def _log_cond(info: str, warning: str, use_info: bool):
    if use_info:
        LOGGER.info(info)
    else:
        LOGGER.warning(warning)


@contextlib.contextmanager
def _nop_context():
    yield


def is_buildable(commit_sha: str, repo: git.Repo) -> bool:
    """Try to build the commit with Maven.

    Args:
        commit_sha: A commit hexsha.
        repo: The related Git repo.
    Returns:
        True if the build was successful.
    """
    with gitutils.saved_git_head(repo):
        repo.git.checkout(commit_sha, "--force")
        return fileutils.mvn_compile(workdir=repo.working_tree_dir)


def is_testable(commit_sha: str, repo: git.Repo) -> bool:
    """Try to run the project's test suite with Maven.

    Args:
        commit_sha: A commit hexsha.
        repo: The related Git repo.
    Returns:
        True if the build was successful.
    """
    with gitutils.saved_git_head(repo):
        repo.git.checkout(commit_sha, "--force")
        return fileutils.mvn_test(workdir=repo.working_tree_dir)


def runtime_benchmark(
    file_merge_dirs: List[pathlib.Path], merge_cmd: str, repeats: int
) -> Iterable[conts.RuntimeResult]:
    for _ in range(repeats):
        for ms, proc in _run_file_merges(file_merge_dirs, merge_cmd):
            assert ms.outcome != conts.MergeOutcome.FAIL

            merge_commit = fileutils.extract_commit_sha(ms.merge_dir)
            base_blob, left_blob, right_blob = [
                gitutils.hash_object(fp)
                for fp in [ms.base_file, ms.left_file, ms.right_file]
            ]

            yield conts.RuntimeResult(
                merge_commit=merge_commit,
                base_blob=base_blob,
                left_blob=left_blob,
                right_blob=right_blob,
                merge_cmd=merge_cmd,
                runtime_ms=ms.runtime,
            )
