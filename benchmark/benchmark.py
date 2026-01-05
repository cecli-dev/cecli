#!/usr/bin/env python3
import asyncio
import datetime
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from json.decoder import JSONDecodeError
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import importlib_resources
import yaml

"""
Performance-oriented refactors:
- Avoid heavy imports unless needed for a given code path.
- Fast path for `--stats` to skip GitPython and benchmarking deps.
- Use json.load for result file parsing to reduce memory churn.
- Cache git version lookups across a single invocation.
"""

# Heavy modules are lazily imported within the code paths that need them.
import typer
from dotenv import load_dotenv
from rich.console import Console

from cecli.dump import dump  # noqa: F401

logger = logging.getLogger("cecli.benchmark")

# Cache for commit-hash -> version lookup
_VERSION_CACHE = {}

BENCHMARK_DNAME = Path(os.environ.get("CECLI_BENCHMARK_DIR", "tmp.benchmarks"))
EXERCISES_DIR_DEFAULT = "cecli-cat"
RESULTS_DIR_DEFAULT = "cat-results"

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


load_dotenv(override=True)


def resolve_dirname(results_dir, use_single_prior, make_new):
    """
    Determines the actual directory path used for storing benchmark results.

    1. Resuming a previous run: If the --cont flag is used and exactly one matching previous run exists,
       it selects that existing directory.
    2. Safety check: If previous runs exist but the user didn't specify --new or --cont,
       it warns the user and aborts to prevent accidental overwrites or confusion.
    3. Creating a new run: If no prior run exists (or --new is used),
       it prepends the current timestamp to the directory name to ensure a unique workspace.
    """
    logger.debug(f"initial results_dir: {results_dir}")
    results_dir = Path(results_dir)
    logger.debug(f"dirname1: {results_dir}")
    if len(results_dir.parts) > 1:
        return results_dir

    priors = list(BENCHMARK_DNAME.glob(f"*--{results_dir}"))
    # BUG20251223
    logger.debug(f"Found priors: {priors}")
    logger.debug(f"use_single_prior: {use_single_prior}, make_new: {make_new}")

    if len(priors) == 1 and use_single_prior:
        results_dir = priors[0].name
        logger.info(f"Using pre-existing {results_dir}")
    elif len(priors):
        if not make_new:
            logger.warning(f"Prior runs of {results_dir} exist, use --new or name one explicitly")
            for prior in priors:
                logger.warning(prior)
            sys.exit(1)

    if not re.match(r"\d\d\d\d-\d\d-\d\d-", str(results_dir)):
        now = datetime.datetime.now()
        now = now.strftime("%Y-%m-%d-%H-%M-%S--")
        results_dir = now + results_dir.name

    logger.debug(f"resolved {results_dir}")
    results_dir = BENCHMARK_DNAME / results_dir
    logger.info(f"updated results_dir: {results_dir}")
    return results_dir


@app.command()
def main(
    results_dir: Optional[str] = typer.Argument("unnamed", help="Results directory slug"),
    model: str = typer.Option("gemini/gemini-3-flash-preview", "--model", "-m", help="Model name"),
    sleep: float = typer.Option(
        0, "--sleep", help="Sleep seconds between tests when single threaded"
    ),
    languages: str = typer.Option(
        None,
        "--languages",
        "-l",
        help="Only run tests for specific languages (comma separated)",
    ),
    edit_format: str = typer.Option(None, "--edit-format", "-e", help="Edit format"),
    editor_model: str = typer.Option(None, "--editor-model", help="Editor model name"),
    editor_edit_format: str = typer.Option(None, "--editor-edit-format", help="Editor edit format"),
    replay: str = typer.Option(
        None,
        "--replay",
        help="Replay previous .cecli.dev.history.md responses from previous benchmark run",
    ),
    keywords: str = typer.Option(
        None,
        "--keywords",
        "-k",
        help="Only run tests that contain keywords (comma sep)",
    ),
    clean: bool = typer.Option(
        False,
        "--clean",
        "-c",
        help="Discard the existing testdir and make a clean copy",
    ),
    cont: bool = typer.Option(False, "--cont", help="Continue the (single) matching testdir"),
    make_new: bool = typer.Option(False, "--new", help="Make a new dated testdir"),
    no_unit_tests: bool = typer.Option(False, "--no-unit-tests", help="Do not run unit tests"),
    no_cecli: bool = typer.Option(False, "--no-cecli", help="Do not run cecli"),
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet output"),
    tries: int = typer.Option(2, "--tries", "-r", help="Number of tries for running tests"),
    threads: int = typer.Option(1, "--threads", "-t", help="Number of threads to run in parallel"),
    num_tests: int = typer.Option(-1, "--num-tests", "-n", help="Number of tests to run"),
    num_ctx: Optional[int] = typer.Option(
        None, "--num-ctx", help="Override model context window size"
    ),
    read_model_settings: str = typer.Option(
        None, "--read-model-settings", help="Load cecli model settings from YAML file"
    ),
    reasoning_effort: Optional[str] = typer.Option(
        None,
        "--reasoning-effort",
        help="Set reasoning effort for models that support it",
    ),
    thinking_tokens: Optional[int] = typer.Option(
        None, "--thinking-tokens", help="Set thinking tokens for models that support it"
    ),
    map_tokens: Optional[int] = typer.Option(
        None,
        "--map-tokens",
        help="Suggested number of tokens for repo map (0 to disable)",
    ),
    exercises_dir: str = typer.Option(
        EXERCISES_DIR_DEFAULT, "--exercises-dir", help="Directory with exercise files"
    ),
    legacy: bool = typer.Option(False, "--legacy", help="Use legacy exercise directory structure"),
    sets: Optional[str] = typer.Option(
        None, "--sets", help="Only run tests for specific sets (comma separated)"
    ),
    hash_re: Optional[str] = typer.Option(
        None,
        "--hash-re",
        help=(
            "Regex to filter exercise hashes. Useful for dividing the set into fractions using"
            " hex chars: '^0' for 1/16, '^[01]' for 1/8, '^[0-3]' for 1/4. Use '^.{n}x' to"
            " match the nth character (e.g., '^.{2}[4-7]' for the 3rd char in range 4-7)."
        ),
    ),
    dry: bool = typer.Option(False, "--dry", help="Run in dry mode (no cecli, no tests)"),
):
    # setup logging and verbosity
    if quiet:
        log_level = logging.WARNING
    elif verbose > 0:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(level=log_level, format="%(message)s")

    from cecli import models

    if dry:
        no_cecli = True
        no_unit_tests = True
        commit_hash = "???????"
    else:
        # Lazy imports for the actual benchmark run
        import git  # Heavy
        import lox  # Only needed for threaded runs

        from cecli import sendchat
        from cecli.coders import base_coder

        repo = git.Repo(search_parent_directories=True)
        commit_hash = repo.head.object.hexsha[:7]
        if repo.is_dirty():
            commit_hash += "-dirty"

    resolved_results_dir = resolve_dirname(results_dir, cont, make_new)

    if not resolved_results_dir:
        logger.error(f"Could not resolve results directory from slug: {results_dir}")
        logger.error(f"Checked in {BENCHMARK_DNAME}")
        return 1
    results_dir = resolved_results_dir

    if not dry and "CECLI_DOCKER" not in os.environ:
        logger.warning("Warning: Benchmarking runs unvetted code. Run in a docker container.")
        logger.warning(
            "Set CECLI_DOCKER in the environment to by-pass this check at your own risk."
        )
        return

    # Check dirs exist
    if not (BENCHMARK_DNAME.exists() and BENCHMARK_DNAME.is_dir()):
        logger.error(f"Benchmark directory not found: {BENCHMARK_DNAME}")
        sys.exit(1)
    original_dname = BENCHMARK_DNAME / exercises_dir
    if not (original_dname.exists() and original_dname.is_dir()):
        logger.error(f"Exercises directory not found: {original_dname}")
        sys.exit(1)

    def legacy_get_exercise_dirs(base_dir, languages=None):
        """Get all exercise directories for specified languages (or all if none specified).
        Uses the legacy `exercises/practice` pattern.
        """
        base_dir = Path(base_dir)
        logger.info(f"Looking for exercises in {base_dir}")

        # Get available language dirs
        lang_dirs = [d for d in base_dir.iterdir() if d.is_dir()]

        # Filter to requested languages if specified
        if languages:
            requested = set(lang.strip().lower() for lang in languages.split(","))
            lang_dirs = [d for d in lang_dirs if d.name.lower() in requested]
            dump(lang_dirs)
            if not lang_dirs:
                logger.warning(f"No matching language directories found for: {languages}")
                return []

        # Get all exercise dirs under exercises/practice for each language
        exercise_dirs = []
        for lang_dir in lang_dirs:
            practice_dir = lang_dir / "exercises" / "practice"
            if practice_dir.exists():
                exercise_dirs.extend(d for d in practice_dir.iterdir() if d.is_dir())

        return exercise_dirs

    def get_exercise_dirs(base_dir, languages=None, sets=None, hash_re=None, legacy=False):
        if legacy:
            return legacy_get_exercise_dirs(base_dir, languages)

        base_dir = Path(base_dir)
        logger.info(f"Scanning for cat.yaml in {base_dir}")

        lang_filter = (
            set(lang.strip().lower() for lang in languages.split(",")) if languages else None
        )
        set_filter = set(sf.strip().lower() for sf in sets.split(",")) if sets else None

        exercise_dirs = []
        for cat_file in base_dir.rglob("cat.yaml"):
            try:
                with open(cat_file, "r") as f:
                    metadata = yaml.safe_load(f)
                    if verbose > 1:
                        logger.debug(f"found {metadata['name']} ({metadata['language']})")
            except Exception as e:
                logger.warning(f"Failed to parse {cat_file}: {e}")
                continue

            if lang_filter and metadata.get("language", "").lower() not in lang_filter:
                continue

            if set_filter:
                cat_sets = set(s.lower() for s in metadata.get("sets", []))
                if not (set_filter & cat_sets):
                    continue

            if hash_re and not re.search(hash_re, metadata.get("hash", "")):
                continue

            exercise_dirs.append(cat_file.parent)

        logger.info(f"Found {len(exercise_dirs)} cats")
        return exercise_dirs

    exercise_dirs = get_exercise_dirs(original_dname, languages, sets, hash_re, legacy=legacy)

    if not exercise_dirs:
        logger.error("No exercise directories found")
        return 1

    if clean and results_dir.exists() and not dry:
        logger.info(f"Cleaning up and replacing {results_dir}")
        dir_files = set(fn.name for fn in results_dir.glob("*"))
        original_files = set(fn.name for fn in original_dname.glob("*"))
        if dir_files != original_files:
            logger.error(
                f"ERROR: will not delete dir that does not look like original tests {results_dir}"
            )
            return

        dest = results_dir.parent / "OLD" / results_dir.name
        if dest.exists():
            old_now = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            dest = results_dir.parent / "OLD" / (old_now + results_dir.name)

        results_dir.rename(dest)

    if not dry:
        if not results_dir.exists():
            logger.info(f"Copying {original_dname} -> {results_dir} ...")
            os.makedirs(results_dir, exist_ok=True)

        copied = False
        for exercise_dir in exercise_dirs:
            dest_dir = results_dir / exercise_dir.name
            if not dest_dir.exists():
                if not copied:
                    logger.info(f"Adding missing exercises to {results_dir} ...")
                shutil.copytree(exercise_dir, dest_dir)
                copied = True
        if copied:
            logger.info("...done")

    test_dnames = sorted(d.name for d in exercise_dirs)

    resource_metadata = importlib_resources.files("cecli.resources").joinpath("model-metadata.json")
    model_metadata_files_loaded = models.register_litellm_models([resource_metadata])
    dump(model_metadata_files_loaded)

    if read_model_settings:
        try:
            files_loaded = models.register_models([read_model_settings])
            if files_loaded:
                logger.debug(f"Loaded model settings from: {files_loaded[0]}")
            else:
                logger.debug(f"No model settings loaded from: {read_model_settings}")
        except Exception as e:
            logger.error(f"Error loading model settings: {e}")
            return 1

    if keywords:
        keywords = keywords.split(",")
        test_dnames = [dn for dn in test_dnames for keyword in keywords if keyword in dn]

    random.shuffle(test_dnames)
    if num_tests > 0:
        test_dnames = test_dnames[:num_tests]

    if not no_cecli:
        # Don't give up when benchmarking
        LONG_TIMEOUT = 24 * 60 * 60
        sendchat.RETRY_TIMEOUT = LONG_TIMEOUT
        base_coder.RETRY_TIMEOUT = LONG_TIMEOUT
        models.RETRY_TIMEOUT = LONG_TIMEOUT

    # Enable in-memory RepoMap cache when running multiple threads to avoid SQLite contention
    repomap_in_memory = threads > 1

    test_args = dict(
        model_name=model,
        edit_format=edit_format,
        tries=tries,
        no_unit_tests=no_unit_tests,
        no_cecli=no_cecli,
        verbose=verbose,
        commit_hash=commit_hash,
        replay=replay,
        editor_model=editor_model,
        editor_edit_format=editor_edit_format,
        num_ctx=num_ctx,
        sleep=sleep,
        reasoning_effort=reasoning_effort,
        thinking_tokens=thinking_tokens,
        map_tokens=map_tokens,
        repomap_in_memory=repomap_in_memory,
        dry=dry,
        results_dir=results_dir,
    )

    if threads > 1:
        run_test_threaded = lox.thread(threads)(run_test)
        for test_path in test_dnames:
            run_test_threaded.scatter(original_dname, results_dir / test_path, **test_args)
        all_results = run_test_threaded.gather(tqdm=True)
    else:
        all_results = []
        for test_path in test_dnames:
            results = run_test(original_dname, results_dir / test_path, **test_args)
            all_results.append(results)
            summarize_results(results_dir, verbose)
            if sleep:
                time.sleep(sleep)

    print()
    print()
    print()
    summarize_results(results_dir, verbose)

    return 0


def load_results(results_dir, stats_languages=None):
    results_dir = Path(results_dir)
    lang_to_results = {}

    # BUG20251223
    logger.debug(f"Globbing {results_dir} for results")
    files = list(results_dir.glob("*/.cecli.results.json"))
    logger.debug(f"Found {len(files)} files")

    for fname in files:
        try:
            results = json.loads(fname.read_text())
            # BUG20251223
            logger.debug(f"Processing result file: {fname}")

            # Try to get language from cat.yaml if it exists in the same dir
            lang = "unknown"
            cat_yaml = fname.parent / "cat.yaml"
            if cat_yaml.exists():
                try:
                    with open(cat_yaml, "r") as f:
                        metadata = yaml.safe_load(f)
                        lang = metadata.get("language", "unknown")
                except Exception:
                    pass

            if stats_languages:
                languages = [lang.strip().lower() for lang in stats_languages.split(",")]
                if lang.lower() not in languages:
                    continue

            logger.debug(f"Derived lang: {lang}")
            lang_to_results.setdefault(lang, []).append(results)
        except json.JSONDecodeError:
            logger.warning(f"json.JSONDecodeError {fname}")
            continue
    return lang_to_results


def summarize_results(results_dir, verbose, stats_languages=None):
    lang_to_results = load_results(results_dir, stats_languages)

    res = SimpleNamespace()
    res.total_tests = len(list(Path(results_dir).glob("*/.cecli.results.json")))

    try:
        tries = max(
            len(results.get("tests_outcomes", []))
            for results_list in lang_to_results.values()
            for results in results_list
            if results
        )
    except ValueError:
        tries = 0

    res.dir_name = str(results_dir)

    passed_tests = [0] * tries

    res.completed_tests = 0
    res.duration = 0
    res.cost = 0
    res.error_outputs = 0
    res.user_asks = 0
    res.test_timeouts = 0
    res.exhausted_context_windows = 0
    res.num_malformed_responses = 0
    res.num_with_malformed_responses = 0
    res.syntax_errors = 0
    res.indentation_errors = 0
    res.lazy_comments = 0
    res.prompt_tokens = 0
    res.completion_tokens = 0

    res.reasoning_effort = None
    res.thinking_tokens = None
    res.map_tokens = None
    variants = defaultdict(set)

    def add(attr_name, increment, global_stats, lang_stats):
        global_prev = getattr(global_stats, attr_name)
        setattr(global_stats, attr_name, global_prev + increment)

        lang_prev = getattr(lang_stats, attr_name)
        setattr(lang_stats, attr_name, lang_prev + increment)

    lang_to_stats = {}
    lang_to_passed_tests = {}
    for lang, results_list in lang_to_results.items():
        lang_stats = SimpleNamespace()
        lang_stats.completed_tests = 0
        lang_stats.duration = 0
        lang_stats.avg_duration_per_test = 0
        lang_stats.cost = 0
        for i in range(tries):
            setattr(lang_stats, f"pass_rate_{i + 1}", 0)
        for i in range(tries):
            setattr(lang_stats, f"pass_num_{i + 1}", 0)
        lang_stats.error_outputs = 0
        lang_stats.user_asks = 0
        lang_stats.test_timeouts = 0
        lang_stats.exhausted_context_windows = 0
        lang_stats.num_malformed_responses = 0
        lang_stats.num_with_malformed_responses = 0
        lang_stats.syntax_errors = 0
        lang_stats.indentation_errors = 0
        lang_stats.lazy_comments = 0
        lang_stats.prompt_tokens = 0
        lang_stats.completion_tokens = 0
        lang_to_stats[lang] = lang_stats
        lang_to_passed_tests[lang] = [0] * tries

        for results in results_list:
            if not results:
                continue

            add("completed_tests", 1, res, lang_stats)
            tests_outcomes = results.get("tests_outcomes", [])
            passed = tests_outcomes and tests_outcomes[-1]
            if passed:
                for i in range(len(tests_outcomes) - 1, tries):
                    passed_tests[i] += 1
                    lang_to_passed_tests[lang][i] += 1

            add("cost", results.get("cost", 0), res, lang_stats)
            add("duration", results.get("duration", 0), res, lang_stats)
            add("test_timeouts", results.get("test_timeouts", 0), res, lang_stats)

            add("error_outputs", results.get("num_error_outputs", 0), res, lang_stats)
            add("user_asks", results.get("num_user_asks", 0), res, lang_stats)
            add(
                "exhausted_context_windows",
                results.get("num_exhausted_context_windows", 0),
                res,
                lang_stats,
            )
            add(
                "num_malformed_responses",
                results.get("num_malformed_responses", 0),
                res,
                lang_stats,
            )
            if results.get("num_malformed_responses"):
                add("num_with_malformed_responses", 1, res, lang_stats)
            add("lazy_comments", results.get("lazy_comments", 0), res, lang_stats)

            add("syntax_errors", results.get("syntax_errors", 0), res, lang_stats)
            add(
                "indentation_errors",
                results.get("indentation_errors", 0),
                res,
                lang_stats,
            )

            add("prompt_tokens", results.get("prompt_tokens", 0), res, lang_stats)
            add(
                "completion_tokens",
                results.get("completion_tokens", 0),
                res,
                lang_stats,
            )

            res.reasoning_effort = results.get("reasoning_effort")
            res.thinking_tokens = results.get("thinking_tokens")
            res.map_tokens = results.get("map_tokens")

            for key in "model edit_format commit_hash editor_model editor_edit_format".split():
                val = results.get(key)
                if val:
                    variants[key].add(val)

    if not res.completed_tests:
        return

    # if res.completed_tests < 133:
    #    return

    console = Console(highlight=False)
    console.rule(title=str(results_dir))

    commit_hashes = variants["commit_hash"]
    versions = get_versions(commit_hashes)
    date = results_dir.name[:10]

    def show(stat, red="red"):
        val = getattr(res, stat)
        style = red if val else None
        console.print(f"  {stat}: {val}", style=style)

    percents = dict()
    for i in range(tries):
        pass_rate = 100 * passed_tests[i] / res.completed_tests
        percents[i] = pass_rate
        # console.print(f"{pass_rate:.1f}% correct after try {i + 1}")
        setattr(res, f"pass_rate_{i + 1}", f"{pass_rate:.1f}")
        setattr(res, f"pass_num_{i + 1}", passed_tests[i])

    print(f"- results_dir: {results_dir.name}")
    style = None if res.completed_tests == res.total_tests else "red"
    console.print(f"  test_cases: {res.completed_tests}", style=style)
    for key, val in variants.items():
        if len(val) > 1:
            style = "red"
        else:
            style = None
        val = ", ".join(map(str, val))
        setattr(res, key, val)
        console.print(f"  {key}: {val}", style=style)

    if res.reasoning_effort is not None:
        print(f"  reasoning_effort: {res.reasoning_effort}")
    if res.thinking_tokens is not None:
        print(f"  thinking_tokens: {res.thinking_tokens}")
    if res.map_tokens is not None:
        print(f"  map_tokens: {res.map_tokens}")

    for i in range(tries):
        print(f"  pass_rate_{i + 1}: {percents[i]:.1f}")
    for i in range(tries):
        print(f"  pass_num_{i + 1}: {passed_tests[i]}")

    pct_well_formed = 1.0 - res.num_with_malformed_responses / res.completed_tests
    print(f"  percent_cases_well_formed: {pct_well_formed * 100:.1f}")

    show("error_outputs")
    show("num_malformed_responses")
    show("num_with_malformed_responses")
    show("user_asks")
    show("lazy_comments")
    show("syntax_errors")
    show("indentation_errors")
    show("exhausted_context_windows")
    show("prompt_tokens", red=None)
    show("completion_tokens", red=None)
    show("test_timeouts")
    print(f"  total_tests: {res.total_tests}")

    if variants["model"]:
        a_model = set(variants["model"]).pop()
        command = f"cecli --model {a_model}"
        print(f"  command: {command}")

    print(f"  date: {date}")
    print("  versions:", ",".join(versions))

    res.avg_duration = res.duration / res.completed_tests
    print(f"  seconds_per_case: {res.avg_duration:.1f}")

    print(f"  total_cost: {res.cost:.4f}")

    res.avg_cost = res.cost / res.completed_tests

    projected_cost = res.avg_cost * res.total_tests

    print()
    print(
        f"costs: ${res.avg_cost:.4f}/test-case, ${res.cost:.2f} total,"
        f" ${projected_cost:.2f} projected"
    )

    if verbose and len(lang_to_stats) > 0:

        def format_lang_stats(lang, lang_stats):
            # First, postprocess attributes for easier printing
            if lang_stats.completed_tests > 0:
                lang_stats.avg_duration_per_test = lang_stats.duration / float(
                    lang_stats.completed_tests
                )
            for i in range(tries):
                num_passed = lang_to_passed_tests[lang][i]
                setattr(lang_stats, f"pass_num_{i + 1}", num_passed)
                pass_rate = 100 * num_passed / float(lang_stats.completed_tests)
                setattr(lang_stats, f"pass_rate_{i + 1}", pass_rate)

            # Then format attributes into ready-to-print strings
            for attr in lang_stats.__dict__:
                val = getattr(lang_stats, attr)
                if val == 0:
                    val = "-"
                elif isinstance(val, float):
                    val = f"{val:,.2f}"
                else:
                    val = f"{val:,}"

                setattr(lang_stats, attr, val)

        def compute_lang_to_col_widths(lang_to_stats):
            lang_to_col_widths = {}
            for lang, lang_stats in lang_to_stats.items():
                lang_stat_attrs = [getattr(lang_stats, attr) for attr in lang_stats.__dict__]
                lang_col_width = max(len(lang), len(max(lang_stat_attrs, key=len)))
                lang_to_col_widths[lang] = lang_col_width

            return lang_to_col_widths

        print()
        print("======== Stats by language ========")
        print()

        [format_lang_stats(lang, lang_stats) for lang, lang_stats in lang_to_stats.items()]
        lang_to_col_widths = compute_lang_to_col_widths(lang_to_stats)

        any_stats = list(lang_to_stats.values())[0]
        attrs = list(any_stats.__dict__)
        attr_col_width = len(max(["language"] + attrs, key=len))
        langs = list(lang_to_stats.keys())

        print("| " + ("-" * attr_col_width), end="")
        for lang in langs:
            col_width = lang_to_col_widths[lang]
            print(" | " + ("-" * col_width), end="")
        print(" |")

        print(f"| {' '.center(attr_col_width)}", end="")
        for lang in langs:
            col_width = lang_to_col_widths[lang]
            print(f" | {lang.center(col_width)}", end="")
        print(" |")

        print("| " + ("-" * attr_col_width), end="")
        for lang in langs:
            col_width = lang_to_col_widths[lang]
            print(" | " + ("-" * col_width), end="")
        print(" |")

        for attr in attrs:
            print(f"| {attr:<{attr_col_width}}", end="")
            for lang in langs:
                lang_stats = lang_to_stats[lang]
                col_width = lang_to_col_widths[lang]
                print(f" | {getattr(lang_stats, attr):>{col_width}}", end="")
            print(" |")

        print("| " + ("-" * attr_col_width), end="")
        for lang in langs:
            col_width = lang_to_col_widths[lang]
            print(" | " + ("-" * col_width), end="")
        print(" |")
        print()

    console.rule()

    # print(json.dumps(vars(res), indent=4, sort_keys=True))
    return res


def get_versions(commit_hashes):
    versions = set()
    for hsh in commit_hashes:
        if not hsh:
            continue
        short = hsh.split("-")[0]
        if short in _VERSION_CACHE:
            ver = _VERSION_CACHE.get(short)
            if ver:
                versions.add(ver)
            continue

        try:
            version_src = subprocess.check_output(
                ["git", "show", f"{short}:cecli/__init__.py"], universal_newlines=True
            )
            match = re.search(r'__version__ = "(.*)"', version_src)
            ver = match.group(1) if match else None
            _VERSION_CACHE[short] = ver
            if ver:
                versions.add(ver)
        except subprocess.CalledProcessError:
            _VERSION_CACHE[short] = None
            pass
    return versions


def get_replayed_content(replay_dname, test_dname):
    replay_dname = Path(replay_dname)
    test_dname = Path(test_dname)
    dump(replay_dname, test_dname)

    test_name = test_dname.name
    replay_fname = replay_dname / test_name / ".cecli.dev.history.md"
    dump(replay_fname)

    res = replay_fname.read_text()
    return res

    res = res.splitlines(keepends=True)
    res = [line for line in res if not line.startswith("> ") and not line.startswith("#### ")]
    return "".join(res)


def run_test(original_dname, testdir, *args, **kwargs):
    try:
        return asyncio.run(run_test_real(original_dname, testdir, *args, **kwargs))
    except Exception:
        logger.error("=" * 40)
        logger.error("Test failed")
        logger.error(traceback.format_exc())

        testdir = Path(testdir)
        results_fname = testdir / ".cecli.results.json"
        results_fname.write_text(json.dumps(dict(exception=traceback.format_exc())))


async def run_test_real(
    original_dname,
    testdir,
    model_name,
    edit_format,
    tries,
    no_unit_tests,
    no_cecli,
    verbose,
    commit_hash,
    replay,
    editor_model,
    editor_edit_format,
    num_ctx=None,
    sleep=0,
    reasoning_effort: Optional[str] = None,
    thinking_tokens: Optional[int] = None,
    map_tokens: Optional[int] = None,
    read_model_settings=None,
    repomap_in_memory: bool = False,
    dry: bool = False,
    results_dir=None,
):
    # Lazy imports: only needed in the actual benchmark execution path
    import git

    import cecli.prompts.utils.system as prompts
    from cecli import models
    from cecli.coders import Coder
    from cecli.io import InputOutput

    if not os.path.isdir(testdir):
        if dry:
            return
        logger.error(f"Not a dir: {testdir}")
        return

    testdir = Path(testdir)

    history_fname = testdir / ".cecli.dev.history.md"

    results_fname = testdir / ".cecli.results.json"
    if results_fname.exists():
        try:
            res = json.loads(results_fname.read_text())
            # if res.get("test_timeouts", 0) > 0:
            #    print(f"{results_fname} test timeouts, redoing...")
            # else:
            return res
        except JSONDecodeError:
            logger.warning(f"{results_fname} failed to parse, redoing...")

    # Read solution and test files from config
    fnames = []
    config_file = testdir / ".meta/config.json"
    if not config_file.exists():
        raise ValueError(f"No config file found: {config_file}")

    with open(config_file) as f:
        config = json.loads(f.read())

    # Get file sets from config
    test_files = config.get("files", {}).get("test", [])
    example_files = config.get("files", {}).get("example", [])
    solution_files = set(config.get("files", {}).get("solution", []))

    # Forcibly ignore certain files not covered by test_files and example_files
    ignore_files = set(
        [
            "CMakeLists.txt",
            "Cargo.toml",
        ]
    )

    # Add all files under .meta and .docs directories
    ignore_files.update(str(p.relative_to(testdir)) for p in testdir.glob(".meta/**/*"))
    ignore_files.update(str(p.relative_to(testdir)) for p in testdir.glob(".docs/**/*"))

    # Also ignore test & example files
    ignore_files.update(test_files)
    ignore_files.update(example_files)

    # Remove any ignore files from the solution set that LLM will edit
    solution_files.difference_update(ignore_files)

    # Try to find original relative path from cat.yaml
    original_rel_path = None
    cat_yaml = testdir / "cat.yaml"
    if cat_yaml.exists():
        try:
            with open(cat_yaml, "r") as f:
                # We need to find where this exercise was in original_dname.
                # Since we don't store the full relative path in cat.yaml,
                # we have to search for it or rely on the fact that we know
                # it was copied from original_dname.
                # A better way is to look for the directory with the same name (hash)
                # in original_dname.
                matches = list(original_dname.rglob(testdir.name))
                if matches:
                    original_rel_path = matches[0].relative_to(original_dname)
        except Exception:
            pass

    # Copy all solution files
    for file_path in solution_files:
        src = testdir / Path(file_path)
        if src.exists():
            fnames.append(src)
            # restore the original file, in case we interrupted a prev run
            # Find the original file in the language-specific practice dir
            if not dry and original_rel_path:
                original_fname = original_dname / original_rel_path / file_path
                if original_fname.exists():
                    os.makedirs(src.parent, exist_ok=True)
                    shutil.copy(original_fname, src)
        else:
            logger.warning(f"Warning: Solution file not found: {src}")

    file_list = " ".join(fname.name for fname in fnames)

    instructions = ""

    introduction = testdir / ".docs/introduction.md"
    if introduction.exists():
        instructions += introduction.read_text()
    instructions += (testdir / ".docs/instructions.md").read_text()
    instructions_append = testdir / ".docs/instructions.append.md"
    if instructions_append.exists():
        instructions += instructions_append.read_text()

    instructions += prompts.instructions_addendum.format(file_list=file_list)

    io = InputOutput(
        pretty=False,
        yes=True,
        chat_history_file=history_fname,
    )

    # weak_model_name = model_name
    weak_model_name = None

    main_model = models.Model(
        model_name,
        weak_model=weak_model_name,
        editor_model=editor_model,
        editor_edit_format=editor_edit_format,
        verbose=verbose,
    )

    if reasoning_effort is not None:
        main_model.set_reasoning_effort(reasoning_effort)

    if thinking_tokens is not None:
        main_model.set_thinking_tokens(thinking_tokens)

    dump(main_model.max_chat_history_tokens)

    if num_ctx:
        if not main_model.extra_params:
            main_model.extra_params = {}
        main_model.extra_params["num_ctx"] = num_ctx
    edit_format = edit_format or main_model.edit_format

    dump(main_model)
    dump(edit_format)
    show_fnames = ",".join(map(str, fnames))
    logger.info(f"fnames: {show_fnames}")
    # Ensure this test directory is a standalone git repo so RepoMap can be used
    if not dry:
        try:
            git_dir = testdir / ".git"
            if not git_dir.exists():
                r = git.Repo.init(testdir)
                # Set a local identity to avoid commit failures in clean containers
                with r.config_writer() as cw:
                    cw.set_value("user", "name", "cecli-benchmark")
                    cw.set_value("user", "email", "cecli-benchmark@example.com")
                # Add existing files (solution set and any current files)
                r.index.add(
                    [str(p.relative_to(testdir)) for p in testdir.rglob("*") if p.is_file()]
                )
                r.index.commit("Initial commit for cecli benchmark")
        except Exception as e:
            logger.debug(f"Warning: failed to initialize git repo in {testdir}: {e}")

    coder_kwargs = dict(
        main_model=main_model,
        edit_format=edit_format,
        io=io,
        fnames=fnames,
        use_git=True,
        auto_commits=False,
        dirty_commits=False,
        stream=False,
        verbose=verbose,
        # auto_lint=False,  # disabled for code-in-json experiments
        cache_prompts=True,
        suggest_shell_commands=False,
        ignore_mentions=ignore_files,
        # Reduce repo map contention and size for benchmarks
        map_cache_dir=str(testdir),
        repomap_in_memory=repomap_in_memory,
        map_mul_no_files=4,
    )
    if map_tokens is not None:
        coder_kwargs["map_tokens"] = map_tokens

    coder = await Coder.create(**coder_kwargs)
    dump(coder.ignore_mentions)

    coder.show_announcements()
    coder.get_file_mentions = lambda x: set()  # No loading of any other files

    timeouts = 0

    syntax_errors = 0
    indentation_errors = 0
    lazy_comments = 0

    dur = 0
    test_outcomes = []
    for i in range(tries):
        start = time.time()

        if no_cecli:
            pass
        elif replay:
            response = get_replayed_content(replay, testdir)
            coder.partial_response_content = response

            show = response.splitlines(keepends=True)
            show = [">> " + line for line in show]
            io.append_chat_history("".join(show))

            await coder.apply_updates()
        else:
            response = await coder.run(with_message=instructions, preproc=False)

        dur += time.time() - start

        if not no_cecli:
            pat = r"^[+]? *[#].* [.][.][.] "
            # Count the number of lines that match pat in response
            dump(response)
            lazy_comments += len(re.findall(pat, response, re.MULTILINE))
            dump(lazy_comments)

        if coder.last_keyboard_interrupt:
            raise KeyboardInterrupt

        if no_unit_tests:
            break

        try:
            errors = run_unit_tests(original_dname, testdir, history_fname, test_files)
        except subprocess.TimeoutExpired:
            # try:
            #    errors = run_unit_tests(original_dname, testdir, history_fname, test_files)
            # except subprocess.TimeoutExpired:
            errors = "Tests timed out!"
            timeouts += 1

        if errors:
            test_outcomes.append(False)
        else:
            test_outcomes.append(True)
            break

        if replay:
            io.append_chat_history(errors)

        errors = errors.splitlines()

        syntax_errors += sum(1 for line in errors if line.startswith("SyntaxError"))
        indentation_errors += sum(1 for line in errors if line.startswith("IndentationError"))

        logger.info(errors[-1])
        errors = "\n".join(errors)
        instructions = errors
        instructions += prompts.test_failures.format(file_list=file_list)

    if not dry:
        # Clean up build directories after all attempts
        # Rust target/debug
        target_dir = testdir / "target" / "debug"
        if target_dir.exists():
            try:
                shutil.rmtree(target_dir)
                logger.debug(f"Cleaned up Rust target/debug directory: {target_dir}")
            except (OSError, shutil.Error, PermissionError) as e:
                logger.debug(f"Failed to clean up Rust target/debug directory: {e}")

        # Java build directories
        java_build_dir = testdir / "build"
        if java_build_dir.exists():
            try:
                shutil.rmtree(java_build_dir)
                logger.debug(f"Cleaned up Java build directory: {java_build_dir}")
            except (OSError, shutil.Error, PermissionError) as e:
                logger.debug(f"Failed to clean up Java build directory: {e}")

        # Node.js node_modules directories
        node_modules_dir = testdir / "node_modules"
        if node_modules_dir.exists():
            try:
                shutil.rmtree(node_modules_dir)
                logger.debug(f"Cleaned up Node.js node_modules directory: {node_modules_dir}")
            except (OSError, shutil.Error, PermissionError) as e:
                logger.debug(f"Failed to clean up Node.js node_modules directory: {e}")

    results = dict(
        testdir=str(testdir),
        testcase=testdir.name,
        model=main_model.name,
        edit_format=edit_format,
        tests_outcomes=test_outcomes,
        cost=coder.total_cost,
        duration=dur,
        test_timeouts=timeouts,
        commit_hash=commit_hash,
        num_error_outputs=io.num_error_outputs,
        num_user_asks=io.num_user_asks,
        num_exhausted_context_windows=coder.num_exhausted_context_windows,
        num_malformed_responses=coder.num_malformed_responses,
        syntax_errors=syntax_errors,
        indentation_errors=indentation_errors,
        lazy_comments=lazy_comments,  # Add the count of pattern matches to the results
        reasoning_effort=reasoning_effort,
        prompt_tokens=coder.total_tokens_sent,
        completion_tokens=coder.total_tokens_received,
        thinking_tokens=thinking_tokens,
        map_tokens=map_tokens,
        chat_hashes=list(
            zip(
                coder.chat_completion_call_hashes,
                coder.chat_completion_response_hashes,
            )
        ),
    )

    if edit_format == "architect":
        results["editor_model"] = main_model.editor_model.name if main_model.editor_model else None
        results["editor_edit_format"] = main_model.editor_edit_format
    dump(results)

    results_fname.write_text(json.dumps(results, indent=4))

    return results


def run_unit_tests(original_dname, testdir, history_fname, test_files):
    timeout = 60 * 3

    # Find original relative path
    original_rel_path = None
    matches = list(original_dname.rglob(testdir.name))
    if matches:
        original_rel_path = matches[0].relative_to(original_dname)

    # Map of file extensions to test commands
    TEST_COMMANDS = {
        ".py": ["pytest"],
        ".rs": ["cargo", "test", "--", "--include-ignored"],
        ".go": ["go", "test", "./..."],
        ".js": ["/cecli/benchmark/npm-test.sh"],
        ".cpp": ["/cecli/benchmark/cpp-test.sh"],
        ".java": ["./gradlew", "test"],
    }

    # Get unique file extensions from test files
    extensions = {Path(f).suffix for f in test_files}

    # Find matching test command
    command = None
    for ext in extensions:
        if ext in TEST_COMMANDS:
            command = TEST_COMMANDS[ext]
            break

    if not command:
        raise ValueError(f"No test command found for files with extensions: {extensions}")

    # Copy test files from original directory
    for file_path in test_files:
        if not original_rel_path:
            break
        src = original_dname / original_rel_path / file_path
        dst = testdir / file_path
        if src.exists():
            logger.info(f"copying {src} {dst}")
            os.makedirs(dst.parent, exist_ok=True)
            shutil.copy(src, dst)

    # Remove @Disabled annotations from Java test files
    for file_path in test_files:
        if file_path.endswith(".java"):
            test_file = testdir / file_path
            if test_file.exists():
                content = test_file.read_text()
                content = re.sub(r"@Disabled\([^)]*\)\s*\n", "", content)
                test_file.write_text(content)

    logger.info(" ".join(command))

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        cwd=testdir,
        encoding="utf-8",
        errors="replace",
    )

    success = result.returncode == 0
    res = result.stdout
    res = cleanup_test_output(res, testdir)
    dump(res)

    with history_fname.open("a") as fh:
        fh.write(f"```\n{res}\n```")

    if not success:
        logger.info(f"Tests failed: {testdir}")
        return res


def cleanup_test_output(output, testdir):
    # remove timing info, to avoid randomizing the response to GPT
    res = re.sub(r"\bin \d+\.\d+s\b", "", output)
    res = res.replace(str(testdir), str(testdir.name))
    return res


if __name__ == "__main__":
    app()
