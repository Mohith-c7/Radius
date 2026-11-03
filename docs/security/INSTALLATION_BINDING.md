# Binding a GitHub App installation to an organization

Status: rule implemented 2026-11 (security review A, finding A-03 and A-05). Product decision pending
for a customer-facing linking flow, see "What is not solved".

## Why the rule exists

Radius uses one GitHub App for every customer. An installation id is a bearer capability: with it the
worker mints an installation token that reads every repository of that installation and writes check runs
and comments. GitHub's `GET /repos/{owner}/{repo}/installation` (App JWT) answers for **any** repository
that has the App installed, whoever asks. A rule of the form "discover the installation of the repository
the caller names and store it on the caller's organization" therefore lets any tenant with a write key
take over another customer's installation by naming one of their repositories. Equally, registering a
numeric GitHub repository id first ("squatting") must not decide where that repository's signed webhooks
go.

## The rule

1. An organization uses **at most one** installation, and an installation belongs to **at most one**
   organization (`organizations.github_installation_id` is unique; the API also checks before writing).
2. `POST /api/v1/repositories/connect-github` works for an organization only through the installation
   **already linked** to it. A repository that GitHub reports under a different installation is
   `409 GITHUB_INSTALLATION_MISMATCH`.
3. An organization with no linked installation gets `403 GITHUB_INSTALLATION_NOT_LINKED`, and GitHub is not
   queried (so the route is no oracle for which private repositories have the App).
4. **Exception, explicit single-tenant dev mode** (`RADIUS_GITHUB_DEV_SINGLE_TENANT`, default **on** only
   when `RADIUS_ENV=development`, off otherwise): an organization with no installation may adopt the
   installation the App has on the requested repository. An installation linked to another organization is
   still never taken. Enable it only on a deployment where exactly one organization uses the App.
5. Webhooks: the tenant is the organization linked to the delivery's installation. If the repository row
   belongs to a different organization the delivery is refused (403), it is not filed under the row's
   owner. A delivery from an installation no organization is linked to is routed by repository ownership,
   and may link the installation, only in explicit single-tenant modes (`GITHUB_SINGLE_TENANT`, or the dev
   mode above); otherwise it is refused (403) until the installation is linked.
6. `POST /api/v1/repositories` never returns or takes over another organization's repository: a
   `repositoryId` already registered by a different organization is `409 REPOSITORY_ALREADY_CONNECTED`
   with no details.

## How an installation gets linked today

- `GITHUB_SINGLE_TENANT=true` plus `GITHUB_DEFAULT_ORGANIZATION_ID`: the first signed webhook of an unlinked
  installation links it to the default organization.
- Development mode (above), or a fixed `GITHUB_INSTALLATION_ID` on the API and worker.
- An operator sets `organizations.github_installation_id` after confirming with the customer which
  GitHub account they installed the App on.

## What is not solved (owner decision needed)

There is no customer-facing proof-of-control flow yet, so a multi-tenant deployment needs the operator step
above. The intended design is the GitHub "Setup URL"/OAuth user-to-server callback: the signed-in Radius
user starts the installation from an authenticated page (state bound to the session and organization),
GitHub redirects back with the `installation_id`, Radius verifies with the user token that this GitHub
user can access that installation, then links it. That needs UI, an OAuth App/permissions decision and a
migration for the state, so it is left open (tracked in `docs/KNOWN_LIMITATIONS.md`).
