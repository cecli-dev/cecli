---
title: Installation
has_children: true
nav_order: 20
description: How to install and get started pair programming with cecli.
---

# Installation
{: .no_toc }


## Get started quickly with cecli-install

{% include get-started.md %}

This will install cecli in its own separate python environment.
If needed, 
cecli-install will also install a separate version of python 3.12 to use with cecli.

Once cecli is installed,
there are also some [optional install steps](/docs/install/optional.html).

See the [usage instructions](https://cecli.dev/docs/usage.html) to start coding with cecli.

## One-liners

These one-liners will install cecli, along with python 3.12 if needed.
They are based on the 
[uv installers](https://docs.astral.sh/uv/getting-started/installation/).

#### Mac & Linux

Use curl to download the script and execute it with sh:

```bash
curl -LsSf https://cecli.dev/install.sh | sh
```

If your system doesn't have curl, you can use wget:

```bash
wget -qO- https://cecli.dev/install.sh | sh
```

#### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://cecli.dev/install.ps1 | iex"
```


## Install with uv

You can install cecli with uv:

```bash
python -m pip install uv  # If you need to install uv
uv tool install --force --python python3.12 --with pip cecli-chat@latest
```

This will install uv using your existing python version 3.8-3.13,
and use it to install cecli.
If needed, 
uv will automatically install a separate python 3.12 to use with cecli.

Also see the
[docs on other methods for installing uv itself](https://docs.astral.sh/uv/getting-started/installation/).

## Install with pipx

You can install cecli with pipx:

```bash
python -m pip install pipx  # If you need to install pipx
pipx install cecli-chat
```

You can use pipx to install cecli with python versions 3.9-3.12.

Also see the
[docs on other methods for installing pipx itself](https://pipx.pypa.io/stable/installation/).

## Other install methods

You can install cecli with the methods described below, but one of the above
methods is usually safer.

#### Install with pip

If you install with pip, you should consider
using a 
[virtual environment](https://docs.python.org/3/library/venv.html)
to keep cecli's dependencies separated.


You can use pip to install cecli with python versions 3.9-3.12.

```bash
python -m pip install -U --upgrade-strategy only-if-needed cecli-chat
```

{% include python-m-aider.md %}

#### Installing with package managers

It's best to install cecli using one of methods
recommended above.
While cecli is available in a number of system package managers,
they often install cecli with incorrect dependencies.

## Next steps...

There are some [optional install steps](/docs/install/optional.html) you could consider.
See the [usage instructions](https://cecli.dev/docs/usage.html) to start coding with cecli.

