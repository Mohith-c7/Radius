"""Analyse a pull request from a public GitHub repo on a local Radius stack.

No GitHub App needed. The script:
  1. reads the repo and the PR from the public GitHub API,
  2. connects the repo to Radius (POST /api/v1/repositories) if it is not connected yet,
  3. sends the PR to Radius as a `pull_request` webhook, which queues an analysis,
  4. the running worker clones the repo and analyses the PR.

Requires a local API with RADIUS_ALLOW_INSECURE_DEV=true and no GITHUB_WEBHOOK_SECRET
(local development only), plus a running worker.

Usage:
    python scripts/analyze_public_pr.py OWNER/REPO PR_NUMBER
    python scripts/analyze_public_pr.py bottlepy/bottle 1450 --dry-run

Set GITHUB_TOKEN to raise GitHub's unauthenticated limit (60 requests/hour).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from uuid import uuid4

DEFAULT_ORG = "00000000-0000-4000-8000-000000000001"


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")
        sys.exit(f"{method} {url} -> HTTP {exc.code}: {text[:500]}")
    except urllib.error.URLError as exc:
        sys.exit(f"{method} {url} failed: {exc.reason} (is the API running?)")


def github(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "radius-local-dev"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return http("GET", f"https://api.github.com{path}", headers=headers)[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", help="OWNER/REPO, e.g. bottlepy/bottle")
    parser.add_argument("pr", type=int, help="pull request number")
    parser.add_argument("--api", default="http://localhost:8000", help="Radius API base URL")
    parser.add_argument("--org", default=DEFAULT_ORG, help="Radius organization id")
    parser.add_argument("--dry-run", action="store_true", help="fetch from GitHub only")
    args = parser.parse_args()

    owner, _, name = args.repo.partition("/")
    if not name:
        sys.exit("repo must look like OWNER/REPO")

    repo = github(f"/repos/{owner}/{name}")
    pr = github(f"/repos/{owner}/{name}/pulls/{args.pr}")
    if repo.get("private"):
        sys.exit("This repo is private; it needs the GitHub App, not this script.")
    print(f"GitHub: {repo['full_name']} (id {repo['id']}), PR #{pr['number']}: {pr['title']}")
    print(f"        {pr['base']['ref']} <- {pr['head']['ref']} @ {pr['head']['sha'][:12]}")
    if args.dry_run:
        print("Dry run: nothing sent to Radius.")
        return

    api = args.api.rstrip("/") + "/api/v1"
    org_headers = {"X-Radius-Organization-Id": args.org}

    _, listed = http("GET", f"{api}/repositories", headers=org_headers)
    existing = [r for r in listed["data"] if r["github_repository_id"] == repo["id"]]
    if existing:
        print(f"Radius: repo already connected ({existing[0]['id']})")
    else:
        _, created = http(
            "POST",
            f"{api}/repositories",
            body={
                "organizationId": args.org,
                "repositoryId": repo["id"],
                "name": repo["name"],
                "owner": repo["owner"]["login"],
                "defaultBranch": repo["default_branch"],
                "cloneUrl": repo["clone_url"],
                "visibility": "public",
            },
            headers=org_headers,
        )
        print(f"Radius: repo connected ({created['data']['id']})")

    action = "opened" if pr["state"] == "open" else "reopened"
    pr_payload = dict(pr, draft=False)
    _, result = http(
        "POST",
        f"{api}/webhooks/github",
        body={"action": action, "number": pr["number"], "pull_request": pr_payload, "repository": repo},
        headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": str(uuid4())},
    )
    data = result.get("data") or {}
    print(f"Radius: webhook accepted: {json.dumps(data)}")
    print("Watch the worker terminal, then open http://localhost:3000/analyses")


if __name__ == "__main__":
    main()
