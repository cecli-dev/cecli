---
parent: Troubleshooting
nav_order: 28
---

# cecli not found

In some environments the `cecli` command may not be available
on your shell path.
This can occur because of permissions/security settings in your OS,
and often happens to Windows users.

You may see an error message like this:

> cecli: The term 'cecli' is not recognized as a name of a cmdlet, function, script file, or executable program. Check the spelling of the name, or if a path was included, verify that the path is correct and try again.

Below is the most fail safe way to run cecli in these situations:

```
python -m cecli
```

You should also consider 
[installing cecli using cecli-install, uv or pipx](/docs/install.html).
