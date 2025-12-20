
# Contributing to the Project

We welcome contributions in the form of bug reports, feature requests,
and pull requests (PRs). This document describes how you can
contribute.

## Bug Reports and Feature Requests

Please submit bug reports as GitHub issues. We would prefer feature requests
be brought directly to the [Discord Chat](https://discord.gg/AX9ZEA7nJn).
This should be faster for triaging feature requests and scoping hem out.


## Pull Requests

We appreciate your pull requests. For small changes, feel free to
submit a PR directly. If you are considering a large or significant
change, please discuss it in the [Discord Chat](https://discord.gg/AX9ZEA7nJn) before submitting the
PR. This will save both you and the maintainers time, and it helps to
ensure that your contributions can be integrated smoothly.

## Setting up the Development Environment

```bash
# Clone the repository
git clone https://github.com/dwash96/aider-ce.git
cd aider-ce

# Make a venv
python3 -m venv venv
source venv/bin/activate

# Install UV because it's superior
pip install uv

# Build Project
uv pip install --native-tls -e .

# Add tool chain
uv install --native-tls pre-commit
pre-commit install

# Run Program
aider-ce

# OR!

cecli

```

### Building the Docker Image

The project includes a `Dockerfile` for building a Docker image. You can build the image by running:

```
docker build -t aider-ce -f docker/Dockerfile .

# OR!

docker build -t cecli -f docker/Dockerfile .
```

## Coding Standards

### Python Compatibility

Aider supports Python versions 3.9, 3.10, 3.11, and 3.12. When contributing code, ensure compatibility with these supported Python versions.

### Code Style

The project follows the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide for Python code, with a maximum line length of 100 characters. Additionally, the project uses [isort](https://pycqa.github.io/isort/) and [Black](https://black.readthedocs.io/en/stable/) for sorting imports and code formatting, respectively. Please install the pre-commit hooks to automatically format your code before committing changes.

### Testing

The project uses [pytest](https://docs.pytest.org/en/latest/) for running unit tests. The test files are located in the `aider/tests` directory and follow the naming convention `test_*.py`.

#### Running Tests

To run the entire test suite, use the following command from the project root directory:

```
pytest
```

You can also run specific test files or test cases by providing the file path or test name:

```
pytest tests/basic/test_coder.py
pytest tests/basic/test_coder.py::TestCoder::test_specific_case
```

#### Continuous Integration

The project uses GitHub Actions for continuous integration. The testing workflows are defined in the following files:

- `.github/workflows/ubuntu-tests.yml`: Runs tests on Ubuntu for Python versions 3.9 through 3.12.
- `.github/workflows/windows-tests.yml`: Runs that on Windows

These workflows are triggered on push and pull request events to the `main` branch, ignoring changes to the `aider/website/**` and `README.md` files.

#### Docker Build and Test

The `.github/workflows/docker-build-test.yml` workflow is used to build a Docker image for the project on every push or pull request event to the `main` branch. It checks out the code, sets up Docker, logs in to DockerHub, and then builds the Docker image without pushing it to the registry.

#### Writing Tests

When contributing new features or making changes to existing code, ensure that you write appropriate tests to maintain code coverage. Follow the existing patterns and naming conventions used in the `aider/tests` directory.

If you need to mock or create test data, consider adding it to the test files or creating separate fixtures or utility functions within the `aider/tests` directory.

#### Test Requirements

The project uses `pytest` as the testing framework, which is installed as a development dependency. To install the development dependencies, run the following command:

```
pip install -r requirements-dev.txt
```

### Managing Dependencies

When introducing new dependencies, make sure to add them to the appropriate `requirements.in` file (e.g., `requirements.in` for main dependencies, `requirements-dev.in` for development dependencies). Then, run the following commands to update the corresponding `requirements.txt` file:

```
pip install pip-tools
./scripts/pip-compile.sh
```

You can also pass one argument to `pip-compile.sh`, which will flow through to `pip-compile`. For example:

```
./scripts/pip-compile.sh --upgrade
```

### Building the Documentation

The project's documentation is built using Jekyll and hosted on GitHub Pages. To build the documentation locally, follow these steps:

1. Install Ruby and Bundler (if not already installed).
2. Navigate to the `aider/website` directory.
3. Install the required gems:
   ```
   bundle install
   ```
4. Build the documentation:
   ```
   bundle exec jekyll build
   ```
5. Preview the website while editing (optional):
   ```
   bundle exec jekyll serve
   ```

The built documentation will be available in the `aider/website/_site` directory.