"""Import skills from the cecli community-resources registry and skills.sh.

Skills are looked up in the community registry (``SKILLS_REGISTRY.json`` in the
``cecli-dev/community-resources`` repo) first, then on skills.sh. A skill is
resolved to a GitHub repo plus a folder path, downloaded from the repo tarball,
and installed into a local ``.cecli/skills`` directory or the global
``~/.cecli/skills`` directory.

Skills resolved from skills.sh are gated on the public security-audit endpoint
(``/api/v1/skills/audit/...``) and are only auto-downloaded when every reported
audit passes. See ``skill_passes_security_audits``.
"""

import io
import json
import re
import ssl
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

REGISTRY_URL = (
    "https://raw.githubusercontent.com/cecli-dev/community-resources/main/SKILLS_REGISTRY.json"
)
REGISTRY_REPO = "cecli-dev/community-resources"
SKILLS_SH_SEARCH_URL = "https://www.skills.sh/api/search"
REGISTRY_CACHE_NAME = "skills_registry.json"
REGISTRY_CACHE_TTL = 60 * 60 * 24  # one day

# Public skills.sh v1 API base. The audit endpoints under it need no auth.
SKILLS_SH_API_BASE = "https://www.skills.sh/api/v1/skills"

# The classic third-party security audits every skills.sh skill must pass before
# we auto-download it. Slugs match the audit endpoint's ``audits[].slug``.
REQUIRED_SECURITY_AUDITS = frozenset({"agent-trust-hub", "socket", "snyk"})


@dataclass
class SkillSource:
    """A resolved skill source: a GitHub repo plus the skill folder path."""

    repo: str
    skill_id: str
    name: str
    source: str


def _cache_dir() -> Path:
    return Path.home() / ".cecli" / "caches"


def _ssl_safe_get(url: str, **kwargs: Any) -> requests.Response:
    """GET a URL, retrying once on the OpenSSL first-init flake.

    On some platforms (observed: WSL2 + OpenSSL 3.5 + Python 3.14) the very
    first ``ssl.create_default_context(...)`` in a fresh process can fail with
    ``ssl.SSLError`` (``[CONF: MODULE_INITIALIZATION_ERROR]`` / "unknown error
    (0x0)") because the OpenSSL CONF module races its lazy initialization. A
    second attempt succeeds. Retrying keeps outbound requests reliable.
    Mirrors llms.runtime.make_client.
    """

    try:
        return requests.get(url, **kwargs)
    except (ssl.SSLError, requests.exceptions.SSLError):
        return requests.get(url, **kwargs)


def get_registry_skills(force: bool = False) -> List[str]:
    """Return the community-registry skill ids, cached for one day."""
    cache_file = _cache_dir() / REGISTRY_CACHE_NAME

    if (
        not force
        and cache_file.exists()
        and time.time() - cache_file.stat().st_mtime < REGISTRY_CACHE_TTL
    ):
        try:
            data = json.loads(cache_file.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass

    try:
        response = _ssl_safe_get(REGISTRY_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data))
            return data
    except Exception:
        pass

    # Fall back to a stale cache when the network request fails.
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return []


def search_skills_sh(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Search skills.sh and return matching skills."""
    try:
        response = _ssl_safe_get(
            SKILLS_SH_SEARCH_URL, params={"q": query, "limit": limit}, timeout=15
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("skills"), list):
            return data["skills"]
    except Exception:
        pass

    return []


def _last_part(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _best_skill_match(matches: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    """Pick the best skills.sh result for a query."""

    def score(item: Dict[str, Any]) -> int:
        name = str(item.get("skillId") or item.get("name") or "").lower()
        query_lower = query.lower()

        if name == query_lower:
            result = 1000
        elif name.startswith(query_lower):
            result = 500
        elif query_lower in name:
            result = 200
        else:
            result = 0

        installs = item.get("installs", 0)
        if isinstance(installs, (int, float)):
            result += int(installs)
        return result

    if not matches:
        return None

    return sorted(matches, key=score, reverse=True)[0]


def resolve_skill(skill_name: str, force: bool = False) -> Optional[SkillSource]:
    """Resolve a skill name to a source, checking the registry then skills.sh."""
    name = (skill_name or "").strip().strip("/")
    if not name:
        return None

    registry = get_registry_skills(force=force)

    if name in registry:
        return SkillSource(
            repo=REGISTRY_REPO, skill_id=name, name=_last_part(name), source="registry"
        )

    last = _last_part(name)
    registry_matches = [rid for rid in registry if _last_part(rid) == last]
    if len(registry_matches) == 1:
        rid = registry_matches[0]
        return SkillSource(
            repo=REGISTRY_REPO, skill_id=rid, name=_last_part(rid), source="registry"
        )

    best = _best_skill_match(search_skills_sh(last), last)
    if best is None:
        return None

    skill_id = str(best.get("skillId") or last)
    return SkillSource(
        repo=best.get("source", ""),
        skill_id=skill_id,
        name=_last_part(skill_id),
        source="skills.sh",
    )


def _parse_skill_name(raw: bytes) -> Optional[str]:
    """Parse the ``name`` field from a SKILL.md frontmatter block."""
    try:
        text = raw.decode("utf-8")
    except Exception:
        return None

    match = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL | re.MULTILINE)
    if not match:
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except Exception:
        return None

    if isinstance(frontmatter, dict) and isinstance(frontmatter.get("name"), str):
        return frontmatter["name"].strip().rstrip("/")

    return None


def _path_score(candidate: str, rel_skill_id: str) -> int:
    """Score how closely a candidate folder matches the requested skill path."""
    if candidate == rel_skill_id:
        return 0
    if candidate.endswith("/" + rel_skill_id):
        return 1
    if candidate.endswith("/skills/" + rel_skill_id):
        return 2
    return 3


def _find_skill_dir(tf, members: List, prefix: str, skill_id: str) -> Optional[str]:
    """Find the repo folder that contains the requested skill."""
    rel_skill_id = skill_id.strip("/")
    last = _last_part(rel_skill_id)
    target: Optional[str] = None

    for member in members:
        if not member.path.endswith("/SKILL.md") or not member.isfile():
            continue
        if not member.path.startswith(prefix + "/"):
            continue

        rel = member.path[len(prefix) + 1 :]
        skill_dir = rel[: -len("/SKILL.md")].rstrip("/")
        if not skill_dir or Path(skill_dir).name != last:
            continue

        raw = b""
        member_file = tf.extractfile(member)
        if member_file is not None:
            raw = member_file.read()
        if _parse_skill_name(raw) != last:
            continue

        if target is None or _path_score(skill_dir, rel_skill_id) < _path_score(
            target, rel_skill_id
        ):
            target = skill_dir

    return target


def download_skill_folder(repo: str, skill_id: str, dest_dir: Path) -> Path:
    """Download a skill folder from a GitHub repo into ``dest_dir``."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://api.github.com/repos/{repo}/tarball/main"
    response = _ssl_safe_get(url, timeout=180, stream=True)
    response.raise_for_status()

    tf = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz")
    members = tf.getmembers()
    prefix = members[0].path.split("/", 1)[0]

    chosen = _find_skill_dir(tf, members, prefix, skill_id)
    if chosen is None:
        raise ValueError(f"Skill '{skill_id}' not found in '{repo}'")

    chosen_prefix = f"{prefix}/{chosen}"
    for member in members:
        if not member.path.startswith(chosen_prefix + "/"):
            continue

        rel = member.path[len(chosen_prefix) + 1 :]
        if not rel:
            continue

        target = dest_dir / rel
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif member.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(member) as src, open(target, "wb") as out:
                out.write(src.read())

    return dest_dir


def fetch_skill_audits(skill_path: str) -> Optional[Dict[str, Any]]:
    """Return the security-audit payload for a skills.sh skill path.

    GETs the public ``/api/v1/skills/audit/{source}/{skill}`` endpoint, which
    requires no auth. Returns ``None`` when the skill has never been audited
    (404) or on any network/HTTP failure.
    """
    url = f"{SKILLS_SH_API_BASE}/audit/{skill_path}"
    try:
        response = _ssl_safe_get(url, timeout=15)
    except Exception:
        return None

    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except Exception:
        return None

    if isinstance(data, dict) and isinstance(data.get("audits"), list):
        return data

    return None


def skill_passes_security_audits(skill_path: str) -> Tuple[bool, str]:
    """Verdict on whether a skills.sh skill passes all security audits.

    A skill passes only when the audit endpoint reports every audit as ``pass``
    *and* the classic three providers (Gen Agent Trust Hub, Socket, Snyk) are all
    present and passing. The check fails closed: missing audits, non-``pass``
    statuses, or a skill that has never been audited (404) all count as not
    passing.
    """
    data = fetch_skill_audits(skill_path)
    if data is None:
        return (
            False,
            f"No security audit results found for '{skill_path}'; refusing to auto-download. "
            "Audits are generated automatically after a skill is installed for the first time.",
        )

    audits = data.get("audits", [])
    by_slug = {str(a.get("slug")): a for a in audits if isinstance(a, dict) and a.get("slug")}

    missing = sorted(REQUIRED_SECURITY_AUDITS - set(by_slug))
    if missing:
        return (
            False,
            f"Missing required security audit(s) ({', '.join(missing)}) for '{skill_path}'.",
        )

    for slug in REQUIRED_SECURITY_AUDITS:
        entry = by_slug[slug]
        if str(entry.get("status", "")).lower() != "pass":
            return (
                False,
                f"Security audit '{entry.get('provider', slug)}' did not pass for "
                f"'{skill_path}' (status: {entry.get('status')}).",
            )

    # Any extra audit (e.g. Runlayer, ZeroLeaks) that is not passing also fails
    # the "all audits pass" bar.
    for entry in audits:
        if isinstance(entry, dict) and str(entry.get("status", "")).lower() != "pass":
            return (
                False,
                f"Security audit '{entry.get('provider')}' did not pass for "
                f"'{skill_path}' (status: {entry.get('status')}).",
            )

    return True, "All security audits pass."


def install_skill(
    skill_name: str, global_install: bool = False, root: Optional[str] = None
) -> Dict[str, Any]:
    """Install a skill into the local or global skills directory."""
    source = resolve_skill(skill_name)
    if source is None:
        return {
            "ok": False,
            "message": f"Skill '{skill_name}' not found in the community registry or on skills.sh.",
        }

    if not source.repo or not source.name:
        return {"ok": False, "message": f"Could not resolve a download source for '{skill_name}'."}

    if source.source == "skills.sh":
        skill_path = f"{source.repo}/{source.skill_id}"
        audits_ok, audits_msg = skill_passes_security_audits(skill_path)
        if not audits_ok:
            return {"ok": False, "message": audits_msg}

    if global_install:
        base = Path.home() / ".cecli" / "skills"
    else:
        anchor = Path(root).expanduser().resolve() if root else Path.cwd()
        base = anchor / ".cecli" / "skills"

    dest_dir = base / source.name

    try:
        download_skill_folder(source.repo, source.skill_id, dest_dir)
    except Exception as e:
        return {"ok": False, "message": f"Failed to download skill '{source.name}': {e}"}

    return {
        "ok": True,
        "name": source.name,
        "skill_id": source.skill_id,
        "source": source.source,
        "dest": str(dest_dir),
    }


def _find_local_config(root: Optional[str] = None) -> Optional[Path]:
    """Find the project ``.cecli.conf.yml`` config file."""
    start = Path(root).expanduser().resolve() if root else Path.cwd()
    for parent in [start] + list(start.parents):
        candidate = parent / ".cecli.conf.yml"
        if candidate.exists():
            return candidate

    home_candidate = Path.home() / ".cecli.conf.yml"
    return home_candidate if home_candidate.exists() else None


def _add_skill_to_config_file(config_path: Path, skill_name: str) -> bool:
    """Add a skill to an existing non-empty ``skills_includelist``. Returns True if changed."""
    if not config_path.exists():
        return False

    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    agent = data.get("agent-config")
    if isinstance(agent, str):
        try:
            agent = json.loads(agent)
        except Exception:
            return False
        data["agent-config"] = agent

    if not isinstance(agent, dict):
        return False

    include_list = agent.get("skills_includelist")
    if not isinstance(include_list, list) or not include_list:
        return False

    if skill_name in include_list:
        return False

    include_list.append(skill_name)
    try:
        config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    except Exception:
        return False

    return True


def add_skill_to_config(skill_name: str, root: Optional[str] = None) -> str:
    """Persist a skill name into a config include-list so it survives restarts."""
    local = _find_local_config(root)
    global_cfg = Path.home() / ".cecli" / "conf.yml"

    if local is not None and _add_skill_to_config_file(local, skill_name):
        return f"Added '{skill_name}' to the include list in {local}."

    if global_cfg.exists() and _add_skill_to_config_file(global_cfg, skill_name):
        return f"Added '{skill_name}' to the include list in {global_cfg}."

    return (
        "No active skills include list found; the skill will be auto-discovered in future sessions."
    )
