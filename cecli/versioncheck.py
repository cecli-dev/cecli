import os
import sys
import time
from pathlib import Path

import packaging.version

import cecli
from cecli import utils
from cecli.dump import dump  # noqa
from cecli.helpers.file_searcher import handle_core_files

VERSION_CHECK_FNAME = handle_core_files(Path.home() / ".cecli" / "caches" / "versioncheck")


async def install_from_main_branch(io):
    """
    Install the latest version of cecli from the main branch of the GitHub repository.
    """
    return await utils.check_pip_install_extra(
        io,
        None,
        "Install the development version of cecli from the main branch?",
        ["git+https://github.com/dwash96/aider-ce.git"],
        self_update=True,
    )


async def install_upgrade(io, latest_version=None):
    """
    Install the latest version of cecli from PyPI.
    """
    if latest_version:
        new_ver_text = f"Newer cecli version v{latest_version} is available."
    else:
        new_ver_text = "Install latest version of cecli?"
    docker_image = os.environ.get("CECLIDOCKER_IMAGE")
    if docker_image:
        text = f"\n{new_ver_text} To upgrade, run:\n\n    docker pull {docker_image}\n"
        io.tool_warning(text)
        return True
    success = await utils.check_pip_install_extra(
        io, None, new_ver_text, ["cecli"], self_update=True
    )
    if success:
        io.tool_output("Re-run cecli to use new version.")
        sys.exit()
    return


async def check_version(io, just_check=False, verbose=False):
    if not just_check and VERSION_CHECK_FNAME.exists():
        day = 60 * 60 * 24
        since = time.time() - os.path.getmtime(VERSION_CHECK_FNAME)
        if 0 < since < day:
            if verbose:
                hours = since / 60 / 60
                io.tool_output(f"Too soon to check version: {hours:.1f} hours")
            return
    import requests

    try:
        response = requests.get("https://pypi.org/pypi/cecli-ce/json")
        data = response.json()
        latest_version = data["info"]["version"]
        current_version = cecli.__version__
        if just_check or verbose:
            io.tool_output(f"Current version: {current_version}")
            io.tool_output(f"Latest version: {latest_version}")
        is_update_available = (
            packaging.version.parse(latest_version).release
            > packaging.version.parse(current_version).release
        )
    except Exception as err:
        io.tool_error(f"Error checking pypi for new version: {err}")
        return False
    finally:
        VERSION_CHECK_FNAME.parent.mkdir(parents=True, exist_ok=True)
        VERSION_CHECK_FNAME.touch()
    if just_check or verbose:
        if is_update_available:
            io.tool_output("Update available")
        else:
            io.tool_output("No update available")
    if just_check:
        return is_update_available
    if not is_update_available:
        return False
    await install_upgrade(io, latest_version)
    return True
