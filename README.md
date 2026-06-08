# github-comments-mcp

The edit/delete comment tools the official [GitHub MCP server](https://github.com/github/github-mcp-server) doesn't have.

`github-mcp-server` can **create** issue and pull-request comments, but it has no tool to **edit** or **delete** an existing one. This is a tiny single-file MCP server that fills exactly that gap by calling the GitHub REST API directly.

## Tools

| Tool | Action | REST endpoint |
|------|--------|---------------|
| `update_issue_comment` | Edit a top-level issue/PR comment | `PATCH /repos/{owner}/{repo}/issues/comments/{id}` |
| `update_review_comment` | Edit an inline PR review comment | `PATCH /repos/{owner}/{repo}/pulls/comments/{id}` |
| `delete_issue_comment` | Delete a top-level issue/PR comment | `DELETE /repos/{owner}/{repo}/issues/comments/{id}` |
| `delete_review_comment` | Delete an inline PR review comment | `DELETE /repos/{owner}/{repo}/pulls/comments/{id}` |

All take `owner`, `repo`, and `comment_id` (the comment's own id — **not** the PR/issue number); the `update_*` tools also take `body` (the new full markdown). Use it alongside the official server: that one to read comment ids and create comments, this one to edit or remove them.

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (dependencies are declared inline via [PEP 723](https://peps.python.org/pep-0723/) — `uv` fetches them on first run; no virtualenv to manage)
- A GitHub token in `GITHUB_PERSONAL_ACCESS_TOKEN` with write access to the target repos (classic `repo`, or fine-grained `pull_requests: write` / `issues: write`)

## Install (Claude Code)

```bash
git clone https://github.com/kaneda-fr/github-comments-mcp.git
claude mcp add -s user github-comments \
  -e 'GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_PERSONAL_ACCESS_TOKEN}' \
  -- uv run --script /absolute/path/to/github-comments-mcp/server.py
```

The token is passed **by reference** (`${VAR}`), so it is resolved from the environment at launch and never written into your MCP config.

### Generic MCP config

```json
{
  "mcpServers": {
    "github-comments": {
      "command": "uv",
      "args": ["run", "--script", "/absolute/path/to/server.py"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}" }
    }
  }
}
```

## Notes

- **Proxies:** the `httpx[socks]` dependency lets the server work behind an HTTP or SOCKS (`ALL_PROXY=socks5h://…`) proxy.
- **Sandboxed hosts:** because `httpx` verifies TLS against its own bundled CA roots, this server works even where Go-based tools relying on the macOS in-process verifier fail (e.g. `gh` returning `x509: OSStatus -26276` inside a restricted sandbox).
- Errors are returned as readable `Error: …` strings (404 / 401 / 403 / 410 / 422) with guidance rather than raw stack traces.

## License

[MIT](./LICENSE)
