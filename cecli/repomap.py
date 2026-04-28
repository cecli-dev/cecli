import math
import os
import re
import shutil
import sqlite3
import sys
import time
import warnings
from collections import defaultdict, namedtuple
from importlib import resources
from pathlib import Path

import tree_sitter
from diskcache import Cache
from pygments.lexers import guess_lexer_for_filename
from pygments.token import Token

from cecli.dump import dump
from cecli.helpers.similarity import (
    cosine_similarity,
    create_bigram_vector,
    normalize_vector,
)
from cecli.special import filter_important_files
from cecli.tools.utils.helpers import ToolError

# tree_sitter is throwing a FutureWarning
warnings.simplefilter("ignore", category=FutureWarning)

from cecli.helpers.grep_ast import TreeContext, filename_to_lang  # noqa: E402
from cecli.helpers.grep_ast.tsl import (  # noqa: E402
    USING_TSL_PACK,
    get_language,
    get_parser,
)


# Define the Tag namedtuple with a default for specific_kind to maintain compatibility
# with cached entries that might have been created with the old definition
class TagBase(
    namedtuple(
        "TagBase",
        "rel_fname fname line name kind specific_kind start_line end_line start_byte end_byte",
    )
):
    __slots__ = ()

    def __new__(
        cls,
        *args,
        rel_fname=None,
        fname=None,
        line=None,
        name=None,
        kind=None,
        specific_kind=None,
        start_line=None,
        end_line=None,
        start_byte=None,
        end_byte=None,
    ):
        # Handle both positional and keyword arguments for backward compatibility
        # with cached data that might have been created with different versions
        if args:
            # Positional arguments provided
            if len(args) >= 1:
                rel_fname = args[0]
            if len(args) >= 2:
                fname = args[1]
            if len(args) >= 3:
                line = args[2]
            if len(args) >= 4:
                name = args[3]
            if len(args) >= 5:
                kind = args[4]
            if len(args) >= 6:
                specific_kind = args[5]
            if len(args) >= 7:
                start_line = args[6]
            if len(args) >= 8:
                end_line = args[7]
            if len(args) >= 9:
                start_byte = args[8]
            if len(args) >= 10:
                end_byte = args[9]

        # Provide default values for backward compatibility
        if specific_kind is None:
            specific_kind = kind
        if start_line is None:
            start_line = line
        if end_line is None:
            end_line = line
        if start_byte is None:
            start_byte = 0
        if end_byte is None:
            end_byte = 0

        return super(TagBase, cls).__new__(
            cls,
            rel_fname,
            fname,
            line,
            name,
            kind,
            specific_kind,
            start_line,
            end_line,
            start_byte,
            end_byte,
        )


Tag = TagBase


SQLITE_ERRORS = (sqlite3.OperationalError, sqlite3.DatabaseError, OSError)


CACHE_VERSION = 7
if USING_TSL_PACK:
    CACHE_VERSION = 9

UPDATING_REPO_MAP_MESSAGE = "Updating repo map"


class RepoMap:
    TAGS_CACHE_DIR = f".cecli/tags.cache.v{CACHE_VERSION}"

    warned_files = set()

    # Class variable to store initial ranked tags results
    _initial_ranked_tags = None
    _initial_ident_to_files = None

    # Define kinds that typically represent definitions across languages
    # Used by AgentCoder to filter tags for the symbol outline
    definition_kinds = {
        "class",
        "struct",
        "enum",
        "interface",
        "trait",  # Structure definitions
        "function",
        "method",
        "constructor",  # Function/method definitions
        "module",
        "namespace",  # Module/namespace definitions
        "constant",
        "variable",  # Top-level/class variable definitions (consider refining)
        "type",  # Type definitions
        # Add more based on tree-sitter queries if needed
    }

    @staticmethod
    def get_file_stub(fname, io, line_numbers=False):
        """Generate a complete structural outline of a source code file.

        Args:
            fname (str): Absolute path to the source file
            io: InputOutput instance for file operations

        Returns:
            str: Formatted outline showing the file's structure
        """
        # Use cached instance if available
        if not hasattr(RepoMap, "_stub_instance"):
            RepoMap._stub_instance = RepoMap(map_tokens=0, io=io)

        rm = RepoMap._stub_instance

        rel_fname = rm.get_rel_fname(fname)

        # Reuse existing tag parsing
        tags = rm.get_tags(fname, rel_fname)
        if not tags:
            return "# No outline available"

        # Get all definition lines
        lois = [tag.line for tag in tags if tag.kind == "def"]

        # Reuse existing tree rendering
        outline = rm.render_tree(fname, rel_fname, lois, line_numbers=line_numbers)

        return f"{outline}"

    def __init__(
        self,
        map_tokens=1024,
        map_cache_dir=".",
        main_model=None,
        io=None,
        repo_content_prefix=None,
        verbose=False,
        max_context_window=None,
        map_mul_no_files=8,
        refresh="auto",
        max_code_line_length=100,
        repo_root=None,
        use_memory_cache=False,
        use_enhanced_map=False,
    ):
        self.io = io
        self.verbose = verbose
        self.refresh = refresh
        self.use_enhanced_map = use_enhanced_map

        self.map_cache_dir = map_cache_dir
        # Prefer an explicit repo root (eg per-test repo), fallback to CWD
        self.root = repo_root or os.getcwd()

        # Allow opting into an in-memory tags cache to avoid disk/SQLite locks
        self.use_memory_cache = use_memory_cache
        if use_memory_cache:
            self.TAGS_CACHE = dict()
        else:
            self.load_tags_cache()
        self.cache_threshold = 0.95

        self.max_map_tokens = map_tokens
        self.map_mul_no_files = map_mul_no_files
        self.max_context_window = max_context_window

        self.max_code_line_length = max_code_line_length

        self.repo_content_prefix = repo_content_prefix

        self.main_model = main_model

        self.tree_cache = {}
        self.tree_context_cache = {}
        self.map_cache = {}
        self.map_processing_time = 0
        self.last_map = None
        # Store single global combined repomap dict (not keyed by cache key)
        self.combined_map_dict = {}

        # Initialize cache for mentioned identifiers similarity
        self._last_mentioned_idents = None
        self._last_mentioned_idents_vector = None
        self._has_last_mentioned_idents = False
        self._mentioned_ident_similarity = 0.8

        if self.verbose:
            self.io.tool_output(f"RepoMap loaded entries from tags cache: {len(self.TAGS_CACHE)}")
            self.io.tool_output(
                f"RepoMap initialized with map_mul_no_files: {self.map_mul_no_files}"
            )
            self.io.tool_output(f"RepoMap initialized with map_cache_dir: {self.map_cache_dir}")
            self.io.tool_output(f"RepoMap assumes repo root is: {self.root}")

    def token_count(self, text):
        len_text = len(text)
        if len_text < 200:
            return self.main_model.token_count(text)

        lines = text.splitlines(keepends=True)
        num_lines = len(lines)
        step = num_lines // 100 or 1
        lines = lines[::step]
        sample_text = "".join(lines)
        sample_tokens = self.main_model.token_count(sample_text)
        est_tokens = sample_tokens / len(sample_text) * len_text
        return est_tokens

    def get_repo_map(
        self,
        chat_files,
        other_files,
        mentioned_fnames=None,
        mentioned_idents=None,
        force_refresh=False,
    ):
        if self.max_map_tokens <= 0:
            return
        if not other_files:
            return
        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        max_map_tokens = self.max_map_tokens

        # With no files in the chat, give a bigger view of the entire repo
        padding = 4096
        if max_map_tokens and self.max_context_window:
            target = min(
                int(max_map_tokens * self.map_mul_no_files),
                self.max_context_window - padding,
            )
        else:
            target = 0
        if not chat_files and self.max_context_window and target > 0:
            max_map_tokens = target

        try:
            combined_dict, new_dict = self.get_ranked_tags_map(
                chat_files,
                other_files,
                max_map_tokens,
                mentioned_fnames,
                mentioned_idents,
                force_refresh,
            )
        except RecursionError:
            self.io.tool_error("Disabling repo map, git repo too large?")
            self.max_map_tokens = 0
            return

        if not combined_dict and not new_dict:
            return

        # For backward compatibility, use combined_dict as files_listing
        files_listing = combined_dict

        if self.verbose:
            # Estimate token count for the dict
            # This is rough - we'd need to format it to get accurate count
            # For now, just note that we have data
            self.io.tool_output(f"Repo-map: generated dict with {len(files_listing)} files")

        if chat_files:
            other = "other "
        else:
            other = ""

        # Return dict with combined dict and new dict for backward compatibility
        return {
            "combined_dict": combined_dict,
            "new_dict": new_dict,
            "files": combined_dict,  # For backward compatibility
            "prefix": (
                self.repo_content_prefix.format(other=other) if self.repo_content_prefix else ""
            ),
            "has_chat_files": bool(chat_files),
        }

    def get_rel_fname(self, fname):
        try:
            return os.path.relpath(fname, self.root)
        except ValueError:
            # Issue #1288: ValueError: path is on mount 'C:', start on mount 'D:'
            # Just return the full fname.
            return fname

    def tags_cache_error(self, original_error=None):
        """Handle SQLite errors by trying to recreate cache, falling back to dict if needed"""

        if self.verbose and original_error:
            self.io.tool_warning(f"Tags cache error: {str(original_error)}")

        if isinstance(getattr(self, "TAGS_CACHE", None), dict):
            return

        path = Path(self.map_cache_dir) / self.TAGS_CACHE_DIR

        # Try to recreate the cache
        try:
            # Delete existing cache dir
            if path.exists():
                shutil.rmtree(path)

            # Try to create new cache
            new_cache = Cache(path)

            # Test that it works
            test_key = "test"
            new_cache[test_key] = "test"
            _ = new_cache[test_key]
            del new_cache[test_key]

            # If we got here, the new cache works
            self.TAGS_CACHE = new_cache
            return

        except SQLITE_ERRORS as e:
            # If anything goes wrong, warn and fall back to dict
            self.io.tool_warning(
                f"Unable to use tags cache at {path}, falling back to memory cache"
            )
            if self.verbose:
                self.io.tool_warning(f"Cache recreation error: {str(e)}")

        self.TAGS_CACHE = dict()

    def load_tags_cache(self):
        path = Path(self.map_cache_dir) / self.TAGS_CACHE_DIR
        try:
            self.TAGS_CACHE = Cache(path)
        except SQLITE_ERRORS as e:
            self.tags_cache_error(e)

    def save_tags_cache(self):
        pass

    def get_mtime(self, fname):
        try:
            return os.path.getmtime(fname)
        except FileNotFoundError:
            self.io.tool_warning(f"File not found error: {fname}")

    def _compute_file_summary(self, tags, rel_fname):
        """Compute file-level summary from tags."""
        defines = set()
        references = defaultdict(int)
        imports = set()

        for tag in tags:
            if tag.kind == "def":
                defines.add(tag.name)
            elif tag.kind == "ref":
                references[tag.name] += 1
            if tag.specific_kind == "import":
                imports.add(tag.name)

        return {"defines": defines, "references": dict(references), "imports": imports}

    def _get_cached_summary(self, fname, file_mtime):
        """Get cached summary for a file if available and up-to-date."""
        cache_key = fname
        try:
            val = self.TAGS_CACHE.get(cache_key)  # Issue #1308
        except SQLITE_ERRORS as e:
            self.tags_cache_error(e)
            val = self.TAGS_CACHE.get(cache_key)

        if val is not None and val.get("mtime") == file_mtime:
            # Handle backward compatibility: old cache entries won't have "summary"
            summary = val.get("summary")
            if summary is None:
                # Compute summary from cached data
                data = val.get("data")
                if data is not None:
                    rel_fname = self.get_rel_fname(fname)
                    summary = self._compute_file_summary(data, rel_fname)
                    # Update cache with summary for future use
                    val["summary"] = summary
                    self.TAGS_CACHE[cache_key] = val
            return summary
        return None

    def get_tags(self, fname, rel_fname):
        # Check if the file is in the cache and if the modification time has not changed
        file_mtime = self.get_mtime(fname)
        if file_mtime is None:
            return []

        cache_key = fname
        try:
            val = self.TAGS_CACHE.get(cache_key)  # Issue #1308
        except SQLITE_ERRORS as e:
            self.tags_cache_error(e)
            val = self.TAGS_CACHE.get(cache_key)

        if val is not None and val.get("mtime") == file_mtime:
            try:
                # Get the cached data
                data = self.TAGS_CACHE[cache_key]["data"]

                # Let our Tag class handle compatibility with old cache formats
                # No need for special handling as TagBase.__new__ will supply default specific_kind

                return data
            except SQLITE_ERRORS as e:
                self.tags_cache_error(e)
                return self.TAGS_CACHE[cache_key]["data"]
            except (TypeError, AttributeError) as e:
                # If we hit an error related to missing fields in old cached Tag objects,
                # force a cache refresh for this file
                if self.verbose:
                    self.io.tool_warning(f"Cache format error for {fname}, refreshing: {e}")
                # Return empty list to trigger cache refresh
                return []

        # miss!
        data = list(self.get_tags_raw(fname, rel_fname))

        # Compute file summary
        summary = self._compute_file_summary(data, rel_fname)

        # Update the cache
        try:
            self.TAGS_CACHE[cache_key] = {"mtime": file_mtime, "data": data, "summary": summary}
            self.save_tags_cache()
        except SQLITE_ERRORS as e:
            self.tags_cache_error(e)
            self.TAGS_CACHE[cache_key] = {"mtime": file_mtime, "data": data, "summary": summary}

        return data

    def get_symbol_definition_location(self, file_path, symbol_name):
        """
        Finds the unique definition location (start/end line) for a symbol in a file.

        Args:
            file_path (str): The relative path to the file.
            symbol_name (str): The name of the symbol to find.

        Returns:
            tuple: (start_line, end_line) (0-based) if a unique definition is found.

        Raises:
            ToolError: If the symbol is not found, not unique, or not a definition.
        """
        abs_path = self.io.root_abs_path(file_path)  # Assuming io has this helper or similar
        rel_path = self.get_rel_fname(abs_path)  # Ensure we use consistent relative path

        tags = self.get_tags(abs_path, rel_path)
        if not tags:
            raise ToolError(f"Symbol '{symbol_name}' not found in '{file_path}' (no tags).")

        definitions = []
        for tag in tags:
            # Check if it's a definition and the name matches
            if tag.kind == "def" and tag.name == symbol_name:
                # Ensure we have valid location info
                if tag.start_line is not None and tag.end_line is not None and tag.start_line >= 0:
                    definitions.append(tag)

        if not definitions:
            # Check if it exists as a non-definition tag
            non_defs = [tag for tag in tags if tag.name == symbol_name and tag.kind != "def"]
            if non_defs:
                raise ToolError(
                    f"Symbol '{symbol_name}' found in '{file_path}', but not as a unique definition"
                    f" (found as {non_defs[0].kind})."
                )
            else:
                raise ToolError(f"Symbol '{symbol_name}' definition not found in '{file_path}'.")

        if len(definitions) > 1:
            # Provide more context about ambiguity if possible
            lines = sorted([d.start_line + 1 for d in definitions])  # 1-based for user message
            raise ToolError(
                f"Symbol '{symbol_name}' is ambiguous in '{file_path}'. Found definitions on lines:"
                f" {', '.join(map(str, lines))}."
            )

        # Unique definition found
        definition_tag = definitions[0]
        return definition_tag.start_line, definition_tag.end_line
        # Check if the file is in the cache and if the modification time has not changed

    def shared_path_components(self, path1_str, path2_str):
        """
        Calculates distance based on how many parent components are shared.
        Distance = Total parts - (2 * Shared parts). Lower is closer.
        """
        p1 = Path(path1_str).parts
        p2 = Path(path2_str).parts

        # Count the number of common leading parts
        common_count = 0
        for comp1, comp2 in zip(p1, p2):
            if comp1 == comp2:
                common_count += 1
            else:
                break

        # A simple metric of difference:
        # (Total parts in P1 + Total parts in P2) - (2 * Common parts)
        distance = len(p1) + len(p2) - (2 * common_count)
        return distance

    def check_import_match(self, definer, imports):
        definer_path = Path(definer)
        definer_parts = list(definer_path.parts)
        if not definer_parts:
            return False

        # Remove extension from last part
        definer_parts[-1] = os.path.splitext(definer_parts[-1])[0]

        for imp in imports:
            imp_parts = [p for p in re.split(r"[.\\/]", imp) if p]
            if len(imp_parts) > len(definer_parts):
                continue

            # Check for sub-sequence match
            # Check for sub-sequence match
            for i in range(len(definer_parts) - len(imp_parts) + 1):
                if definer_parts[i : i + len(imp_parts)] == imp_parts:
                    # Allow if it's a suffix match (standard aliasing)
                    if i + len(imp_parts) == len(definer_parts):
                        return True

                    # Allow partial/middle match if enough specificity (>= 2 parts)
                    if len(imp_parts) >= 2:
                        return True
        return False

    def get_tags_raw(self, fname, rel_fname):
        lang = filename_to_lang(fname)
        if not lang:
            return

        try:
            language = get_language(lang)
            parser = get_parser(lang)
        except Exception as err:
            if self.verbose:
                print(f"Skipping file {fname}: {err}")
            return

        query_scm = get_scm_fname(lang)
        if not query_scm.exists():
            return
        query_scm = query_scm.read_text()

        code = self.io.read_text(fname)
        if not code:
            return
        tree = parser.parse(bytes(code, "utf-8"))

        # Run the tags queries
        if sys.version_info >= (3, 10):
            query = tree_sitter.Query(language, query_scm)
            cursor = tree_sitter.QueryCursor(query)
            captures = cursor.captures(tree.root_node)
        else:
            query = language.query(query_scm)
            captures = query.captures(tree.root_node)

        saw = set()
        if USING_TSL_PACK:
            all_nodes = []
            for tag, nodes in captures.items():
                all_nodes += [(node, tag) for node in nodes]
        else:
            all_nodes = list(captures)

        for node, tag in all_nodes:
            if tag.startswith("name.definition."):
                kind = "def"
            elif tag.startswith("name.reference."):
                kind = "ref"
            else:
                continue

            saw.add(kind)

            # Extract specific kind from the tag, e.g., 'function' from 'name.definition.function'
            specific_kind = tag.split(".")[-1] if "." in tag else None

            result = Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=node.text.decode("utf-8"),
                kind=kind,
                specific_kind=specific_kind,
                line=node.start_point[0],  # Legacy line number
                start_line=node.start_point[0],
                end_line=node.end_point[0],
                start_byte=node.start_byte,
                end_byte=node.end_byte,
            )

            yield result

        if "ref" in saw:
            return
        if "def" not in saw:
            return

        # We saw defs, without any refs
        # Some tags files only provide defs (cpp, for example)
        # Use pygments to backfill refs

        try:
            lexer = guess_lexer_for_filename(fname, code)
        except Exception:  # On Windows, bad ref to time.clock which is deprecated?
            # self.io.tool_error(f"Error lexing {fname}")
            return

        tokens = list(lexer.get_tokens(code))
        tokens = [token[1] for token in tokens if token[0] in Token.Name]

        for token in tokens:
            yield Tag(
                rel_fname=rel_fname,
                fname=fname,
                name=token,
                kind="ref",
                specific_kind="name",  # Default for pygments fallback
                line=-1,  # Pygments doesn't give precise locations easily
                start_line=-1,
                end_line=-1,
                start_byte=-1,
                end_byte=-1,
            )

    def get_ranked_tags(
        self, chat_fnames, other_fnames, mentioned_fnames, mentioned_idents, progress=True
    ):
        import rustworkx

        defines = defaultdict(set)
        references = defaultdict(lambda: defaultdict(int))
        total_ref_count = defaultdict(int)  # Track total references per identifier
        definitions = defaultdict(set)
        file_imports = defaultdict(set)
        import_ast_mode = False

        personalization = dict()

        fnames = set(chat_fnames).union(set(other_fnames))
        chat_rel_fnames = set()

        fnames = sorted(fnames)

        # Default personalization for unspecified files is 1/num_nodes
        personalize = 100 / len(fnames)

        fname_to_parts = {}
        fname_to_suffix = {}

        try:
            cache_size = len(self.TAGS_CACHE)
        except SQLITE_ERRORS as e:
            self.tags_cache_error(e)
            cache_size = len(self.TAGS_CACHE)

        if len(fnames) - cache_size > 100:
            self.io.tool_output(
                "Initial repo scan can be slow in larger repos, but only happens once."
            )
            self.io.update_spinner("Scanning repo")
            showing_bar = True
        else:
            showing_bar = False

        num_fnames = len(fnames)
        fname_index = 0
        for fname in fnames:
            if self.verbose:
                self.io.tool_output(f"Processing {fname}")
            if progress:
                if showing_bar:
                    fname_index += 1
                    self.io.update_spinner(f"Scanning repo: {fname_index}/{num_fnames}")
                else:
                    self.io.update_spinner(f"{UPDATING_REPO_MAP_MESSAGE}: {fname}")

            try:
                file_ok = os.path.isfile(fname)
            except OSError:
                file_ok = False

            if not file_ok:
                if fname not in self.warned_files:
                    self.io.tool_warning(f"Repo-map can't include {fname}")
                    self.io.tool_output(
                        "Has it been deleted from the file system but not from git?"
                    )
                    self.warned_files.add(fname)
                continue

            # dump(fname)
            rel_fname = self.get_rel_fname(fname)
            current_pers = 0.0  # Start with 0 personalization score

            if fname in chat_fnames:
                current_pers += personalize
                chat_rel_fnames.add(rel_fname)

            if rel_fname in mentioned_fnames:
                # Use max to avoid double counting if in chat_fnames and mentioned_fnames
                current_pers = max(current_pers, personalize)

            # Check path components against mentioned_idents
            path_obj = Path(rel_fname)
            fname_to_parts[rel_fname] = path_obj.parts
            fname_to_suffix[rel_fname] = path_obj.suffix
            path_components = set(path_obj.parts)
            basename_with_ext = path_obj.name
            basename_without_ext, _ = os.path.splitext(basename_with_ext)
            components_to_check = path_components.union({basename_with_ext, basename_without_ext})

            matched_idents = components_to_check.intersection(mentioned_idents)
            if matched_idents:
                # Add personalization *once* if any path component matches a mentioned ident
                current_pers += personalize

            if current_pers > 0:
                personalization[rel_fname] = current_pers  # Assign the final calculated value

            # Get file mtime and check for cached summary
            file_mtime = self.get_mtime(fname)
            summary = None
            if file_mtime is not None:
                summary = self._get_cached_summary(fname, file_mtime)

            if summary is not None:
                # Use cached summary for defines and references
                for ident in summary["defines"]:
                    defines[ident].add(rel_fname)
                for ident, count in summary["references"].items():
                    references[ident][rel_fname] += count
                    total_ref_count[ident] += count
                for imp in summary["imports"]:
                    file_imports[rel_fname].add(imp)

                # Still need to parse tags for definitions (Tag objects)
                # But only if this file has definitions
                if summary["defines"]:
                    tags = list(self.get_tags(fname, rel_fname))
                    if tags is not None:
                        for tag in tags:
                            if tag.kind == "def":
                                key = (rel_fname, tag.name)
                                definitions[key].add(tag)
            else:
                # No cached summary, parse all tags
                tags = list(self.get_tags(fname, rel_fname))
                if tags is None:
                    continue

                for tag in tags:
                    if tag.kind == "def":
                        defines[tag.name].add(rel_fname)
                        key = (rel_fname, tag.name)
                        definitions[key].add(tag)

                    elif tag.kind == "ref":
                        references[tag.name][rel_fname] += 1
                        total_ref_count[tag.name] += 1

                    if tag.specific_kind == "import":
                        file_imports[rel_fname].add(tag.name)

        self.io.profile("Process Files")

        if self.use_enhanced_map and len(file_imports) > 0:
            import_ast_mode = True

        if len(references) == 0:
            # Convert defines to the new references structure: dict of dicts with counts
            references = {}
            for ident, files in defines.items():
                references[ident] = {file: 1 for file in files}
                total_ref_count[ident] = len(files)  # Each file has count 1

        idents = set(defines.keys()).intersection(set(references.keys()))

        G = rustworkx.PyDiGraph(multigraph=True)

        # Collect all unique file names that will be nodes
        all_files = set()
        for files in defines.values():
            all_files.update(files)
        for ref_dict in references.values():
            all_files.update(ref_dict.keys())
        all_files.update(file_imports.keys())
        all_files.update(personalization.keys())

        # Add all nodes and create mapping from file name to node index
        file_to_node = {}
        node_to_file = {}
        for fname in sorted(all_files):
            node_idx = G.add_node(fname)
            file_to_node[fname] = node_idx
            node_to_file[node_idx] = fname

        # Add a small self-edge for every definition that has no references
        # Helps with tree-sitter 0.23.2 with ruby, where "def greet(name)"
        # isn't counted as a def AND a ref. tree-sitter 0.24.0 does.

        unreferenced_weight = 2**-32 / (len(idents) + 1)
        for ident in defines.keys():
            if ident in references:
                continue
            for definer in defines[ident]:
                definer_idx = file_to_node[definer]
                G.add_edge(
                    definer_idx, definer_idx, {"weight": unreferenced_weight, "ident": ident}
                )

        for ident in idents:
            if progress:
                self.io.update_spinner(f"{UPDATING_REPO_MAP_MESSAGE}: {ident}")

            definers = defines[ident]

            mul = 1.0

            is_snake = ("_" in ident) and any(c.isalpha() for c in ident)
            is_kebab = ("-" in ident) and any(c.isalpha() for c in ident)
            is_camel = any(c.isupper() for c in ident) and any(c.islower() for c in ident)
            if ident in mentioned_idents:
                mul *= 16

            # Prioritize function-like identifiers
            if (
                (is_snake or is_kebab or is_camel)
                and len(ident) >= 8
                and "test" not in ident.lower()
            ):
                mul *= 16

            # Downplay repetitive definitions in case of common boiler plate
            # Scale down logarithmically given the increasing number of references in a codebase
            # Ideally, this will help downweight boiler plate in frameworks, interfaces, and abstract classes
            if len(defines[ident]) > 4:
                exp = min(len(defines[ident]), 32)
                mul *= math.log2((4 / (2**exp)) + 1)

            # Calculate multiplier: log(number of unique file references * total references ^ 2)
            # Used to balance the number of times an identifier appears with its number of refs per file
            # Penetration in code base is important
            # So is the frequency
            # And the logarithm keeps them from scaling out of bounds forever
            # Combined with the above downweighting
            # There should be a push/pull that balances repetitiveness of identifier defs
            # With absolute number of references throughout a codebase
            unique_file_refs = len(references[ident])
            total_refs = total_ref_count[ident]
            ext_mul = round(math.log2(unique_file_refs * total_refs**2 + 1))

            for referencer, num_refs in references[ident].items():
                relevant_definers = [] if import_ast_mode else definers

                # A referencer should not link to any definiers of an identifier it also defines
                if referencer in definers:
                    relevant_definers = [referencer]
                elif import_ast_mode:
                    if referencer in file_imports:
                        matches = [
                            d
                            for d in definers
                            if self.check_import_match(d, file_imports[referencer])
                        ]
                        if matches:
                            relevant_definers = matches

                for definer in relevant_definers:
                    # dump(referencer, definer, num_refs, mul)
                    # Only add edge if file extensions match
                    referencer_ext = fname_to_suffix[referencer]
                    definer_ext = fname_to_suffix[definer]
                    if referencer_ext != definer_ext:
                        continue

                    use_mul = mul * ext_mul

                    if referencer in chat_rel_fnames:
                        use_mul *= 64
                    elif referencer == definer:
                        use_mul *= num_refs / 128

                    # scale down so high freq (low value) mentions don't dominate
                    # num_refs = math.sqrt(num_refs)

                    p1 = fname_to_parts[referencer]
                    p2 = fname_to_parts[definer]

                    # Count common leading parts
                    common_count = 0
                    for c1, c2 in zip(p1, p2):
                        if c1 == c2:
                            common_count += 1
                        else:
                            break

                    path_distance = len(p1) + len(p2) - (2 * common_count)

                    weight = use_mul * 2 ** (-1 * path_distance)
                    referencer_idx = file_to_node[referencer]
                    definer_idx = file_to_node[definer]
                    G.add_edge(
                        referencer_idx,
                        definer_idx,
                        {"weight": weight, "key": ident, "ident": ident},
                    )

        self.io.profile("Build Graph")

        self.io.profile("PERSONALIZATION START")
        # Convert personalization from file names to node indices
        if personalization:
            pers_node = {file_to_node[fname]: val for fname, val in personalization.items()}
            pers_args = dict(personalization=pers_node, dangling=pers_node)
        else:
            pers_args = dict()
        self.io.profile("PERSONALIZATION END")
        try:
            ranked = rustworkx.pagerank(G, weight_fn=lambda edge: edge["weight"], **pers_args)
        except ZeroDivisionError:
            # Issue #1536
            try:
                ranked = rustworkx.pagerank(G, weight_fn=lambda edge: edge["weight"])
            except ZeroDivisionError:
                self.io.profile("zero")
                return []
            except Exception as e:
                self.io.profile(e)
        except Exception as e:
            self.io.profile(e)

        self.io.profile("PageRank")

        # distribute the rank from each source node, across all of its out edges
        ranked_definitions = defaultdict(float)
        for src in G.node_indices():
            if progress:
                self.io.update_spinner(f"{UPDATING_REPO_MAP_MESSAGE}: {src}")

            src_rank = ranked[src]
            total_weight = sum(data["weight"] for _src, _dst, data in G.out_edges(src))
            # dump(src, src_rank, total_weight)
            for _src, dst, data in G.out_edges(src):
                data["rank"] = src_rank * data["weight"] / total_weight
                ident = data["ident"]
                fname = node_to_file[dst]
                ranked_definitions[(fname, ident)] += data["rank"]

        self.io.profile("Distribute Rank")

        ranked_tags = []
        ranked_definitions = sorted(
            ranked_definitions.items(), reverse=True, key=lambda x: (x[1], x[0])
        )

        # with open('defs.txt', 'w') as out_file:
        #     import pprint
        #     printer = pprint.PrettyPrinter(indent=2, stream=out_file)
        #     printer.pprint(ranked_definitions)

        for (fname, ident), rank in ranked_definitions:
            # print(f"{rank:.03f} {fname} {ident}")
            if fname in chat_rel_fnames:
                continue
            ranked_tags += list(definitions.get((fname, ident), []))

        rel_other_fnames_without_tags = set(self.get_rel_fname(fname) for fname in other_fnames)

        fnames_already_included = set(rt[0] for rt in ranked_tags)

        top_rank = sorted([(rank, node_idx) for (node_idx, rank) in ranked.items()], reverse=True)
        for rank, node_idx in top_rank:
            fname = node_to_file[node_idx]
            if fname in rel_other_fnames_without_tags:
                rel_other_fnames_without_tags.remove(fname)
            if fname not in fnames_already_included:
                ranked_tags.append((fname,))

        for fname in rel_other_fnames_without_tags:
            ranked_tags.append((fname,))

        return ranked_tags

    def get_ranked_tags_map(
        self,
        chat_fnames,
        other_fnames=None,
        max_map_tokens=None,
        mentioned_fnames=None,
        mentioned_idents=None,
        force_refresh=False,
    ):
        if not other_fnames:
            other_fnames = list()
        if not max_map_tokens:
            max_map_tokens = self.max_map_tokens
        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        # Create a cache key
        cache_key = [max_map_tokens]

        if self.refresh == "auto":
            # Handle mentioned_fnames normally
            cache_key += [
                tuple(sorted(mentioned_fnames)) if mentioned_fnames else None,
            ]

            # Handle mentioned_idents with similarity check
            cache_key_component = self._get_mentioned_idents_cache_component(mentioned_idents)
            cache_key.append(cache_key_component)
        else:
            cache_key += [
                tuple(sorted(chat_fnames)) if chat_fnames else None,
                len(other_fnames) if other_fnames else None,
            ]

        cache_key = hash(str(tuple(cache_key)))

        use_cache = False
        if not force_refresh:
            if self.refresh == "manual" and self.last_map:
                return self.last_map

            if self.refresh == "always":
                use_cache = False
            elif self.refresh == "files":
                use_cache = True
            elif self.refresh == "auto":
                use_cache = self.map_processing_time > 1.0

            # Check if the result is in the cache
            if use_cache and cache_key in self.map_cache:
                return self.map_cache[cache_key]

        # If not in cache or force_refresh is True, generate the map
        start_time = time.time()

        # Get the current global combined dict
        combined_dict = self.combined_map_dict

        # Generate new dict and updated combined dict
        combined_dict_updated, new_dict = self.get_ranked_tags_map_uncached(
            chat_fnames,
            other_fnames,
            max_map_tokens,
            mentioned_fnames,
            mentioned_idents,
            combined_dict,
        )
        end_time = time.time()
        self.map_processing_time = end_time - start_time

        # Store the updated combined dict globally
        self.combined_map_dict = combined_dict_updated

        # Create the return value (tuple)
        return_value = (combined_dict_updated, new_dict)

        # Store the result in the cache
        self.map_cache[cache_key] = return_value
        self.last_map = return_value

        return return_value

    def get_ranked_tags_map_uncached(
        self,
        chat_fnames,
        other_fnames=None,
        max_map_tokens=None,
        mentioned_fnames=None,
        mentioned_idents=None,
        combined_dict=None,
    ):
        self.io.profile("Start Rank Tags Map Uncached", start=True)

        if not other_fnames:
            other_fnames = list()
        if not max_map_tokens:
            max_map_tokens = self.max_map_tokens
        if not mentioned_fnames:
            mentioned_fnames = set()
        if not mentioned_idents:
            mentioned_idents = set()

        self.io.update_spinner(UPDATING_REPO_MAP_MESSAGE)

        ranked_tags = self.get_ranked_tags(
            chat_fnames, other_fnames, mentioned_fnames, mentioned_idents, True
        )

        self.io.profile("Finish Getting Ranked Tags")

        other_rel_fnames = sorted(set(self.get_rel_fname(fname) for fname in other_fnames))
        special_fnames = filter_important_files(other_rel_fnames)
        ranked_tags_fnames = set(tag[0] for tag in ranked_tags)
        special_fnames = [fn for fn in special_fnames if fn not in ranked_tags_fnames]
        special_fnames = [(fn,) for fn in special_fnames]

        ranked_tags = special_fnames + ranked_tags

        # Build file -> tags dict
        current_tokens = 0

        # Estimate tokens per tag entry: filename + tag name + kind + line info
        # Rough estimate: each tag entry ~16 tokens

        chat_rel_fnames = set(self.get_rel_fname(fname) for fname in chat_fnames)

        # Generate full dict (without skipping based on combined_dict)
        full_dict = {}
        current_tokens = 0

        for tag in ranked_tags:
            if isinstance(tag, tuple) and len(tag) == 1:
                # Special file without tags: (fname,)
                rel_fname = tag[0]
                if rel_fname in chat_rel_fnames:
                    continue
                if rel_fname not in full_dict:
                    full_dict[rel_fname] = {}
                # Special files don't count towards token limit
                continue

            # Regular Tag object
            rel_fname = tag.rel_fname
            if rel_fname in chat_rel_fnames:
                continue

            if rel_fname not in full_dict:
                full_dict[rel_fname] = {}

            tag_name = tag.name
            kind = tag.kind
            specific_kind = tag.specific_kind
            line = tag.line
            start_line = tag.start_line
            end_line = tag.end_line

            # Use specific_kind if available, otherwise kind
            display_kind = specific_kind if specific_kind else kind

            full_dict[rel_fname][tag_name] = {
                "kind": display_kind,
                "line": line,
                "start_line": start_line,
                "end_line": end_line,
            }

            # Count this tag towards token limit
            current_tokens += 16
            if current_tokens >= max_map_tokens:
                break

        # Compute new_dict: items in full_dict but not in combined_dict
        new_dict = {}
        if combined_dict is None:
            combined_dict = {}

        for rel_fname, tags_info in full_dict.items():
            if rel_fname not in combined_dict:
                # New file
                new_dict[rel_fname] = tags_info.copy()
            else:
                # Check for new tags in existing file
                new_tags = {}
                for tag_name, tag_info in tags_info.items():
                    if tag_name not in combined_dict[rel_fname]:
                        new_tags[tag_name] = tag_info
                if new_tags:
                    new_dict[rel_fname] = new_tags

        # Update combined_dict with new items
        combined_dict_updated = combined_dict.copy()
        for rel_fname, tags_info in new_dict.items():
            if rel_fname not in combined_dict_updated:
                combined_dict_updated[rel_fname] = tags_info.copy()
            else:
                combined_dict_updated[rel_fname].update(tags_info)

        self.io.profile("Calculate Best Tree")

        return combined_dict_updated, new_dict

    tree_cache = dict()

    def render_tree(self, abs_fname, rel_fname, lois, line_numbers=False):
        mtime = self.get_mtime(abs_fname)
        key = (rel_fname, tuple(sorted(lois)), mtime)

        if key in self.tree_cache:
            return self.tree_cache[key]

        if (
            rel_fname not in self.tree_context_cache
            or self.tree_context_cache[rel_fname]["mtime"] != mtime
        ):
            code = self.io.read_text(abs_fname) or ""
            if not code.endswith("\n"):
                code += "\n"

            context = TreeContext(
                rel_fname,
                code,
                color=False,
                line_number=line_numbers,
                child_context=False,
                last_line=False,
                margin=0,
                mark_lois=False,
                loi_pad=0,
                # header_max=30,
                show_top_of_file_parent_scope=False,
            )
            self.tree_context_cache[rel_fname] = {"context": context, "mtime": mtime}

        context = self.tree_context_cache[rel_fname]["context"]
        context.lines_of_interest = set()
        context.add_lines_of_interest(lois)
        context.add_context()
        res = context.format()
        self.tree_cache[key] = res
        return res

    def to_tree(self, tags, chat_rel_fnames):
        if not tags:
            return ""

        cur_fname = None
        cur_abs_fname = None
        lois = None
        output = ""

        # add a bogus tag at the end so we trip the this_fname != cur_fname...
        dummy_tag = (None,)
        for tag in sorted(tags) + [dummy_tag]:
            this_rel_fname = tag[0]
            if this_rel_fname in chat_rel_fnames:
                continue

            # ... here ... to output the final real entry in the list
            if this_rel_fname != cur_fname:
                if lois is not None:
                    output += "\n"
                    output += cur_fname + ":\n"

                    # truncate long lines, in case we get minified js or something else crazy
                    output += truncate_long_lines(
                        self.render_tree(cur_abs_fname, cur_fname, lois), self.max_code_line_length
                    )

                    lois = None
                elif cur_fname:
                    output += "\n" + cur_fname + "\n"
                if type(tag) is Tag:
                    lois = []
                    cur_abs_fname = tag.fname
                cur_fname = this_rel_fname

            if lois is not None:
                lois.append(tag.line)

        return output

    def _get_mentioned_idents_cache_component(self, mentioned_idents):
        """
        Determine the cache key component for mentioned_idents using similarity comparison.

        This method compares the current mentioned_idents with the previous ones using
        cosine similarity. If the similarity is high enough, it returns the previous
        cache key component to maintain cache hits. Otherwise, it updates the stored
        values and returns the current mentioned_idents.

        Args:
            mentioned_idents (set): Current set of mentioned identifiers

        Returns:
            tuple or None: Cache key component for mentioned_idents
        """
        if not mentioned_idents:
            self._last_mentioned_idents = None
            self._last_mentioned_idents_vector = None
            self._has_last_mentioned_idents = False
            return None

        current_mentioned_idents = tuple(mentioned_idents)

        # Check if we have a previous cached value to compare against
        if self._has_last_mentioned_idents:
            # Create vector for current mentioned_idents
            current_vector = create_bigram_vector(current_mentioned_idents)
            current_vector_norm = normalize_vector(current_vector)

            # Calculate cosine similarity
            similarity = cosine_similarity(self._last_mentioned_idents_vector, current_vector_norm)
            # If similarity is high enough, use the previous cache key component
            if similarity >= self._mentioned_ident_similarity:
                # Use the previous mentioned_idents for cache key to maintain cache hit
                cache_key_component = self._last_mentioned_idents

                # Make similarity more strict the more consecutive cache hits
                self._mentioned_ident_similarity = min(
                    0.9, self._mentioned_ident_similarity + 0.025
                )
            else:
                # Similarity is too low, use current mentioned_idents
                cache_key_component = current_mentioned_idents

                # Update stored values
                self._last_mentioned_idents = current_mentioned_idents
                self._last_mentioned_idents_vector = current_vector_norm

                # Make similarity less strict the more consecutive cache misses
                self._mentioned_ident_similarity = max(
                    0.5, self._mentioned_ident_similarity - 0.025
                )
        else:
            # First time or no previous value, use current mentioned_idents
            cache_key_component = current_mentioned_idents
            current_vector = create_bigram_vector(current_mentioned_idents)

            # Store for future comparisons
            self._last_mentioned_idents = current_mentioned_idents
            self._last_mentioned_idents_vector = normalize_vector(current_vector)

        self._has_last_mentioned_idents = True
        return cache_key_component


def truncate_long_lines(text, max_length):
    return "\n".join([line[:max_length] for line in text.splitlines()]) + "\n"


def find_src_files(directory):
    if not os.path.isdir(directory):
        return [directory]

    src_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            src_files.append(os.path.join(root, file))
    return src_files


def get_scm_fname(lang):
    # Load the tags queries
    if USING_TSL_PACK:
        subdir = "tree-sitter-language-pack"
        try:
            path = resources.files(__package__).joinpath(
                "queries",
                subdir,
                f"{lang}-tags.scm",
            )
            if path.exists():
                return path
        except KeyError:
            pass

    # Fall back to tree-sitter-languages
    subdir = "tree-sitter-languages"
    try:
        return resources.files(__package__).joinpath(
            "queries",
            subdir,
            f"{lang}-tags.scm",
        )
    except KeyError:
        return


def get_supported_languages_md():
    from cecli.helpers.grep_ast.parsers import PARSERS

    res = """
| Language | File extension | Repo map | Linter |
|:--------:|:--------------:|:--------:|:------:|
"""
    data = sorted((lang, ex) for ex, lang in PARSERS.items())

    for lang, ext in data:
        fn = get_scm_fname(lang)
        repo_map = "✓" if fn and os.path.exists(fn) else ""
        linter_support = "✓"
        res += f"| {lang:20} | {ext:20} | {repo_map:^8} | {linter_support:^6} |\n"

    res += "\n"

    return res


if __name__ == "__main__":
    fnames = sys.argv[1:]

    chat_fnames = []
    other_fnames = []
    for fname in sys.argv[1:]:
        if os.path.isdir(fname):
            chat_fnames += find_src_files(fname)
        else:
            chat_fnames.append(fname)

    rm = RepoMap(root=".")
    repo_map = rm.get_ranked_tags_map(chat_fnames, other_fnames)

    dump(len(repo_map))
    print(repo_map)
