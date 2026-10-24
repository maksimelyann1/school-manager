"""Export the actual registered tool catalog for review and release handoff."""
import asyncio
import json
from pathlib import Path

try:
    from .server import create_server
except ImportError:
    from server import create_server


async def main():
    tools = await create_server().list_tools()
    target = Path(__file__).resolve().parents[2] / "docs/mcp-tools.json"
    catalog = {"transport": "stdio", "tool_count": len(tools), "tools": [
        {"name": t.name, "description": t.description,
         "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else {},
         "input_schema": t.inputSchema} for t in tools]}
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Registered tools: {len(tools)}; catalog: {target}")


if __name__ == "__main__":
    asyncio.run(main())
