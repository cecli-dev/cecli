# Code Signing Policy

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

Windows release artifacts for the **cecli desktop application** (`ce-underscore`, branded **ce_** in the interface) are signed with this certificate. The desktop application is a shell that drives the `cecli` coding agent in Agent Client Protocol (ACP) mode; both are part of this project and built from the source code in this repository. Release builds run in the [Desktop Release workflow](.github/workflows/desktop-release.yml) on GitHub-hosted runners from `v*` tags, and every signing request is manually approved before a release is published.

Each release signs the installed application executable (`ce-underscore.exe`) first, then the NSIS installer that bundles it (`cecli_<version>_x64-setup.exe`, published as `ce-underscore_<version>_x64-setup.exe`). The installer and the application executable both carry the product metadata `cecli`. The uninstaller that the installer generates at installation time is not signed. Artifacts signed with the test certificate are staged on draft releases only and are never published publicly; the workflow signs with the `test-signing` policy until the release certificate is approved, then switches to `release-signing`, and a release is published only after both release-signing requests complete.

Only artifacts built from this repository are signed. Third-party components bundled inside the installer (for example the [uv](https://github.com/astral-sh/uv) sidecar) are upstream open-source binaries and are not signed with this certificate. On first launch, the desktop application uses uv to install the `cecli` runtime from PyPI; that runtime is built and published by this project.

## Release pipeline configuration

Windows signing is controlled by repository variables in the [Desktop Release workflow](.github/workflows/desktop-release.yml):

- `SIGNPATH_SIGNING_POLICY_SLUG`: SignPath signing policy to use. Defaults to `test-signing` while the release certificate is pending. Once the release certificate is approved, the repository variable will be set to `release-signing` to switch release signing without changing the workflow. Certificate trust is not enforced for non-release policies.
- `SIGNPATH_ORGANIZATION_ID` and `SIGNPATH_PROJECT_SLUG`: SignPath organization and project identifiers.

## Team roles

- **Authors, committers, and reviewers**: [cecli-dev organization members](https://github.com/orgs/cecli-dev/people). Authors may modify the source directly; every change from a non-committer is proposed as a pull request and reviewed by a member before it is merged. Changes to build scripts and CI workflows receive the same review as application code.
- **Approvers**: [cecli-dev organization owners](https://github.com/orgs/cecli-dev/people?query=role%3Aowner). The current signing approver is Dustin Washington ([@dwash96](https://github.com/dwash96)). Each signing request requires approval by a team member.

All maintainers use multi-factor authentication for both GitHub and SignPath accounts.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it. Requests to model providers or other services are only made to endpoints configured by the user.

## Scope

This policy covers the Windows application executable and the Windows installers for the cecli desktop application built by this repository. Packages published to [PyPI](https://pypi.org/project/cecli-dev/) and Linux/macOS artifacts are not Authenticode-signed.
