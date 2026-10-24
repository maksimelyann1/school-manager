"""Set timeouts in only this MCP server's existing TOML section."""
from pathlib import Path
import re
import tomllib


def configure(path: Path):
    source = path.read_text(encoding="utf-8-sig")
    parsed = tomllib.loads(source)
    if "school_manager" not in parsed.get("mcp_servers", {}):
        raise RuntimeError("Register school_manager with codex mcp add first")
    match = re.search(r"(?m)^\[mcp_servers\.school_manager\][ \t]*\r?$", source)
    if not match:
        raise RuntimeError("Cannot locate the exact school_manager TOML section")
    next_section = re.search(r"(?m)^\[", source[match.end():])
    end = match.end() + next_section.start() if next_section else len(source)
    body = source[match.end():end]
    body = re.sub(r"(?m)^[ \t]*(startup_timeout_sec|tool_timeout_sec)[ \t]*=.*(?:\r?\n|$)", "", body)
    updated = source[:match.end()] + "\nstartup_timeout_sec = 20\ntool_timeout_sec = 360" + body + source[end:]
    final = tomllib.loads(updated)
    before, after = parsed["mcp_servers"]["school_manager"].copy(), final["mcp_servers"]["school_manager"].copy()
    for name in ("startup_timeout_sec", "tool_timeout_sec"):
        before.pop(name, None)
        after.pop(name, None)
    assert before == after
    if updated != source:
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    import os
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    configure(root / "config.toml")
    print("school_manager MCP timeouts configured: startup 20s, tool 360s")
