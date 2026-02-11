#!/usr/bin/env python3
"""Update README SVG stat labels from GitHub GraphQL data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


GRAPHQL_URL = "https://api.github.com/graphql"
DEFAULT_SVGS = [
    "assets/readme-template/readme-top-light-template.svg",
    "assets/readme-template/readme-top-dark-template.svg",
]
DEFAULT_CACHE = "tools/readme_stats_cache.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update README SVG stats")
    parser.add_argument("--username", required=True, help="GitHub username/login")
    parser.add_argument(
        "--svg",
        action="append",
        dest="svg_paths",
        default=[],
        help="Path to SVG file to update (repeatable)",
    )
    parser.add_argument(
        "--cache-path",
        default=DEFAULT_CACHE,
        help="Path to cache JSON file (default: tools/readme_stats_cache.json)",
    )
    return parser.parse_args()


def resolve_token() -> str:
    token = (
        os.getenv("GH_STATS_TOKEN")
        or os.getenv("GITHUB_TOKEN")
        or os.getenv("ACCESS_TOKEN")
    )
    if not token:
        raise RuntimeError(
            "Missing token. Set GH_STATS_TOKEN (preferred) or GITHUB_TOKEN."
        )
    return token


def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "readme-stats-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GraphQL HTTP {exc.code}: {detail}") from exc
    data = json.loads(body)
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


def query_user_basics(token: str, login: str) -> dict[str, Any]:
    query = """
    query($login: String!) {
      user(login: $login) {
        id
        followers { totalCount }
        repositories(ownerAffiliations: OWNER, isFork: false) { totalCount }
        repositoriesContributedTo(
          contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
          includeUserRepositories: true
        ) { totalCount }
      }
    }
    """
    data = graphql(token, query, {"login": login})
    user = data.get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {login}")
    return user


def query_owned_repos(token: str, login: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    cursor: str | None = None
    query = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(
          first: 100
          after: $cursor
          ownerAffiliations: OWNER
          isFork: false
          orderBy: {field: UPDATED_AT, direction: DESC}
        ) {
          nodes {
            nameWithOwner
            stargazerCount
            defaultBranchRef {
              target { ... on Commit { oid } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    while True:
        data = graphql(token, query, {"login": login, "cursor": cursor})
        page = data["user"]["repositories"]
        repos.extend(page.get("nodes") or [])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return repos


def query_contributed_repos(token: str, login: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    cursor: str | None = None
    query = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositoriesContributedTo(
          first: 100
          after: $cursor
          includeUserRepositories: true
          contributionTypes: [COMMIT]
          orderBy: {field: PUSHED_AT, direction: DESC}
        ) {
          nodes {
            nameWithOwner
            defaultBranchRef {
              target { ... on Commit { oid } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """
    while True:
        data = graphql(token, query, {"login": login, "cursor": cursor})
        page = data["user"]["repositoriesContributedTo"]
        repos.extend(page.get("nodes") or [])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return repos


def query_repo_commit_loc(
    token: str, owner: str, name: str, author_id: str
) -> tuple[int, int, int]:
    """Return (commit_count, additions, deletions) for author on repo default branch."""
    query = """
    query($owner: String!, $name: String!, $authorId: ID!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100, after: $cursor, author: {id: $authorId}) {
                totalCount
                nodes { additions deletions }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
      }
    }
    """
    commits = 0
    adds = 0
    dels = 0
    cursor: str | None = None
    got_total = False
    while True:
        data = graphql(
            token,
            query,
            {"owner": owner, "name": name, "authorId": author_id, "cursor": cursor},
        )
        repo = data.get("repository")
        if not repo or not repo.get("defaultBranchRef"):
            return (0, 0, 0)
        history = repo["defaultBranchRef"]["target"]["history"]
        if not got_total:
            commits = int(history.get("totalCount") or 0)
            got_total = True
        for node in history.get("nodes") or []:
            adds += int(node.get("additions") or 0)
            dels += int(node.get("deletions") or 0)
        if not history["pageInfo"]["hasNextPage"]:
            break
        cursor = history["pageInfo"]["endCursor"]
    return (commits, adds, dels)


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"repos": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"repos": {}}


def save_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def split_name_with_owner(name_with_owner: str) -> tuple[str, str]:
    owner, name = name_with_owner.split("/", 1)
    return owner, name


def update_xml_text(root: ET.Element, element_id: str, value: str) -> None:
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = value


def dots_for_width(formatted_value: str, width: int) -> str:
    remaining = max(0, width - len(formatted_value))
    if remaining <= 2:
        return {0: "", 1: " ", 2: ". "}[remaining]
    return " " + ("." * remaining) + " "


def fmt_num(value: int) -> str:
    return f"{value:,}"


def update_svg(svg_path: Path, stats: dict[str, int]) -> None:
    tree = ET.parse(svg_path)
    root = tree.getroot()

    fields = [
        ("repo_data", stats["repo_count"], 6),
        ("star_data", stats["star_count"], 14),
        ("commit_data", stats["commit_count"], 22),
        ("follower_data", stats["follower_count"], 10),
        ("loc_data", stats["loc_total"], 9),
    ]
    for element_id, num, width in fields:
        text = fmt_num(num)
        update_xml_text(root, element_id, text)
        update_xml_text(root, f"{element_id}_dots", dots_for_width(text, width))

    update_xml_text(root, "contrib_data", fmt_num(stats["contrib_repo_count"]))
    update_xml_text(root, "loc_add", fmt_num(stats["loc_add"]))
    loc_del_text = fmt_num(stats["loc_del"])
    update_xml_text(root, "loc_del", loc_del_text)
    update_xml_text(root, "loc_del_dots", dots_for_width(loc_del_text, 7))

    tree.write(svg_path, encoding="utf-8", xml_declaration=True)


def collect_repo_stats(
    token: str,
    author_id: str,
    owned_repos: list[dict[str, Any]],
    contributed_repos: list[dict[str, Any]],
    cache: dict[str, Any],
) -> tuple[int, int, int, dict[str, Any]]:
    repo_map: dict[str, dict[str, Any]] = {}
    for repo in owned_repos + contributed_repos:
        name_with_owner = repo.get("nameWithOwner")
        if not name_with_owner:
            continue
        target = ((repo.get("defaultBranchRef") or {}).get("target") or {})
        oid = target.get("oid")
        owner, name = split_name_with_owner(name_with_owner)
        repo_map[name_with_owner] = {"owner": owner, "name": name, "oid": oid}

    cached_repos: dict[str, Any] = cache.get("repos", {})
    new_cache: dict[str, Any] = {"repos": {}}
    total_commits = 0
    total_adds = 0
    total_dels = 0

    for full_name in sorted(repo_map.keys()):
        info = repo_map[full_name]
        oid = info["oid"]
        cached = cached_repos.get(full_name) or {}

        if (
            oid
            and cached.get("oid") == oid
            and all(k in cached for k in ("commits", "additions", "deletions"))
        ):
            commits = int(cached["commits"])
            adds = int(cached["additions"])
            dels = int(cached["deletions"])
        else:
            commits, adds, dels = query_repo_commit_loc(
                token, info["owner"], info["name"], author_id
            )

        total_commits += commits
        total_adds += adds
        total_dels += dels
        new_cache["repos"][full_name] = {
            "oid": oid,
            "commits": commits,
            "additions": adds,
            "deletions": dels,
        }

    return total_commits, total_adds, total_dels, new_cache


def main() -> int:
    args = parse_args()
    token = resolve_token()
    svg_paths = [Path(p) for p in (args.svg_paths or DEFAULT_SVGS)]

    basics = query_user_basics(token, args.username)
    owned_repos = query_owned_repos(token, args.username)
    contributed_repos = query_contributed_repos(token, args.username)

    star_count = sum(int(repo.get("stargazerCount") or 0) for repo in owned_repos)
    cache_path = Path(args.cache_path)
    cache = load_cache(cache_path)

    commit_count, loc_add, loc_del, new_cache = collect_repo_stats(
        token=token,
        author_id=basics["id"],
        owned_repos=owned_repos,
        contributed_repos=contributed_repos,
        cache=cache,
    )
    save_cache(cache_path, new_cache)

    stats = {
        "repo_count": int(basics["repositories"]["totalCount"]),
        "contrib_repo_count": int(basics["repositoriesContributedTo"]["totalCount"]),
        "star_count": star_count,
        "commit_count": commit_count,
        "follower_count": int(basics["followers"]["totalCount"]),
        "loc_add": loc_add,
        "loc_del": loc_del,
        "loc_total": loc_add - loc_del,
    }

    for svg_path in svg_paths:
        if not svg_path.exists():
            raise RuntimeError(f"SVG path not found: {svg_path}")
        update_svg(svg_path, stats)

    print(json.dumps({"username": args.username, "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
