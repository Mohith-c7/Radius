# Governance

Radius is currently a single-owner project. This file describes how decisions are made today so contributors know what to expect. It will change as the project grows.

## Roles

- **Owner**: decides scope and direction, promotes to `dev` and `main`, grants and removes maintainer rights. See [MAINTAINERS.md](MAINTAINERS.md).
- **Maintainers**: review and merge pull requests into `develop` once the owner has granted that right.
- **Contributors**: anyone who opens an issue, discussion or pull request. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).

## How decisions are made

- Significant decisions (architecture, licensing, data handling, branching, anything hard to reverse) are written down as numbered entries in [docs/decisions.md](docs/decisions.md), with alternatives considered and a "revisit when" condition. A recorded decision can be reopened with a new entry that supersedes it.
- Everyday changes are decided in pull-request review. A maintainer approves; the owner breaks ties.
- Releases are promoted `develop` -> `dev` (UAT) -> `main` by the owner only (DEC-005).
- Security reports follow [SECURITY.md](SECURITY.md); conduct reports follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Changing governance

Propose changes by pull request to this file. The owner decides. If the project gains regular outside maintainers, expect this document to move to a documented maintainer process.
