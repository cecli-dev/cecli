"""Shared lookups for the ``/hooks`` subcommands."""


def hook_names(coder):
    """Return the names of every registered hook."""
    from cecli.hooks.service import HookService

    hook_manager = HookService.get_manager(coder)
    all_hooks = hook_manager.get_all_hooks()

    names = []
    for hooks in all_hooks.values():
        for hook in hooks:
            names.append(hook.name)

    return names
