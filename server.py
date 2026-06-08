#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0", "httpx[socks]>=0.27"]
# ///
'''
MCP server for editing and deleting GitHub comments.

Fills the single gap in the official `github-mcp-server`: it can *create* issue/PR
comments but has no tool to **edit** or **delete** an existing one. This server adds
the four missing operations (update/delete for both top-level issue/PR comments and
inline pull-request review comments) by calling the GitHub REST API directly.

Auth: reads a token from GITHUB_PERSONAL_ACCESS_TOKEN. Runs unsandboxed when spawned
by the Claude Code host; httpx verifies TLS against its own (certifi) bundle, so it is
unaffected by the sandbox TLS issue that blocks `gh`.
'''

import os
from typing import Annotated, Any

import httpx
from pydantic import Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("github_comments_mcp")

# Constants
API_BASE_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
TOKEN_ENV = "GITHUB_PERSONAL_ACCESS_TOKEN"
TIMEOUT = 30.0

# Reusable validated parameter types (flat args → idiomatic, un-nested schema)
Owner = Annotated[str, Field(description="Repository owner (org or user), e.g. 'octocat'", min_length=1, max_length=100)]
Repo = Annotated[str, Field(description="Repository name, e.g. 'hello-world'", min_length=1, max_length=200)]
CommentId = Annotated[int, Field(description="Numeric comment id — the comment's own id/databaseId, NOT the PR/issue number", ge=1)]
Body = Annotated[str, Field(description="The new full markdown body to replace the comment with", min_length=1)]


# --- Shared helpers ---------------------------------------------------------
def _headers() -> dict[str, str]:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(
            f"{TOKEN_ENV} is not set. Configure it in the MCP server env so this server can authenticate to GitHub."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "github-comments-mcp",
    }


async def _request(method: str, path: str, json_body: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=TIMEOUT) as client:
        resp = await client.request(method, path, headers=_headers(), json=json_body)
    resp.raise_for_status()
    return resp


def _error(e: Exception, kind: str) -> str:
    '''Map exceptions to actionable, agent-friendly messages.'''
    if isinstance(e, RuntimeError):
        return f"Error: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 404:
            return (
                f"Error: {kind} comment not found (404). Check the comment_id is the comment's own id "
                "(from the comment object), not the PR/issue number, and that owner/repo are correct."
            )
        if code in (401, 403):
            return (
                f"Error: not authorized ({code}) to modify this {kind} comment. The token needs write access "
                "(repo / pull_requests:write) and must own the comment or have maintainer rights."
            )
        if code == 410:
            return f"Error: this {kind} comment is gone (410) — it was already deleted."
        if code == 422:
            return f"Error: GitHub rejected the request (422): {e.response.text[:300]}"
        return f"Error: GitHub API request failed with status {code}: {e.response.text[:300]}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: request to GitHub timed out. Try again."
    return f"Error: unexpected {type(e).__name__}: {e}"


# --- Tools ------------------------------------------------------------------
@mcp.tool(
    name="update_issue_comment",
    annotations={
        "title": "Edit an issue/PR top-level comment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def update_issue_comment(owner: Owner, repo: Repo, comment_id: CommentId, body: Body) -> str:
    '''Edit the body of an existing **top-level** issue or pull-request comment in place.

    Top-level PR comments are issue comments (PRs are issues), so this covers the
    "edit the marker comment in place" pattern (e.g. a review-cycle-summary comment).
    The official github MCP can only *create* these — use this to update one.

    Args:
        owner (str): Repository owner (org or user).
        repo (str): Repository name.
        comment_id (int): The comment's own id (not the PR/issue number).
        body (str): New full markdown body.

    Returns:
        str: "Updated issue comment <id>: <html_url>" on success, or "Error: ..." with guidance.

    Examples:
        - Use when: re-running a review and the `<!-- claude-review-cycle-summary:v1 -->` comment
          already exists — fetch its id, then update it here.
        - Don't use for: inline code-review comments (use update_review_comment);
          creating a new comment (use the github MCP's add_issue_comment).
    '''
    try:
        r = await _request("PATCH", f"/repos/{owner}/{repo}/issues/comments/{comment_id}", {"body": body})
        return f"Updated issue comment {comment_id}: {r.json().get('html_url', '(no url)')}"
    except Exception as e:  # noqa: BLE001 - mapped to actionable message
        return _error(e, "issue")


@mcp.tool(
    name="update_review_comment",
    annotations={
        "title": "Edit a PR inline review comment",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def update_review_comment(owner: Owner, repo: Repo, comment_id: CommentId, body: Body) -> str:
    '''Edit the body of an existing **inline** pull-request review comment in place.

    Inline review comments are the ones anchored to a file:line in a PR diff
    (the `/pulls/comments/{id}` resource), distinct from top-level issue comments.

    Args:
        owner (str): Repository owner (org or user).
        repo (str): Repository name.
        comment_id (int): The review comment's own id.
        body (str): New full markdown body.

    Returns:
        str: "Updated review comment <id>: <html_url>" on success, or "Error: ..." with guidance.

    Examples:
        - Use when: revising a published inline review note.
        - Don't use for: top-level PR/issue comments (use update_issue_comment).
    '''
    try:
        r = await _request("PATCH", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}", {"body": body})
        return f"Updated review comment {comment_id}: {r.json().get('html_url', '(no url)')}"
    except Exception as e:  # noqa: BLE001
        return _error(e, "review")


@mcp.tool(
    name="delete_issue_comment",
    annotations={
        "title": "Delete an issue/PR top-level comment",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def delete_issue_comment(owner: Owner, repo: Repo, comment_id: CommentId) -> str:
    '''Delete an existing **top-level** issue or pull-request comment. This cannot be undone.

    Args:
        owner (str): Repository owner (org or user).
        repo (str): Repository name.
        comment_id (int): The comment's own id.

    Returns:
        str: "Deleted issue comment <id>." on success, or "Error: ..." with guidance.

    Examples:
        - Use when: removing a stale/duplicate marker comment.
        - Don't use for: inline review comments (use delete_review_comment).
    '''
    try:
        await _request("DELETE", f"/repos/{owner}/{repo}/issues/comments/{comment_id}")
        return f"Deleted issue comment {comment_id}."
    except Exception as e:  # noqa: BLE001
        return _error(e, "issue")


@mcp.tool(
    name="delete_review_comment",
    annotations={
        "title": "Delete a PR inline review comment",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def delete_review_comment(owner: Owner, repo: Repo, comment_id: CommentId) -> str:
    '''Delete an existing **inline** pull-request review comment. This cannot be undone.

    Args:
        owner (str): Repository owner (org or user).
        repo (str): Repository name.
        comment_id (int): The review comment's own id.

    Returns:
        str: "Deleted review comment <id>." on success, or "Error: ..." with guidance.

    Examples:
        - Use when: retracting a published inline review note.
        - Don't use for: top-level PR/issue comments (use delete_issue_comment).
    '''
    try:
        await _request("DELETE", f"/repos/{owner}/{repo}/pulls/comments/{comment_id}")
        return f"Deleted review comment {comment_id}."
    except Exception as e:  # noqa: BLE001
        return _error(e, "review")


if __name__ == "__main__":
    mcp.run()
