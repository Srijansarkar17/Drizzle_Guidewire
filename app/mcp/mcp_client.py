"""
MCP Client — lightweight wrapper for calling MCP tool servers.
Used internally by risk_service.py. This module handles the HTTP
communication protocol with MCP-compatible servers.
"""

import logging
from typing import Optional

import httpx

from app.core.config import settings

log = logging.getLogger("drizzle.mcp_client")


MCP_SERVERS = {
    "weather": {
        "base_url": settings.WEATHER_MCP_URL.replace("/score", ""),
        "score_endpoint": "/score",
        "health_endpoint": "/health",
        "tools_endpoint": "/mcp/tools",
        "call_endpoint": "/mcp/call",
    },
    "traffic": {
        "base_url": settings.TRAFFIC_MCP_URL.replace("/score", ""),
        "score_endpoint": "/score",
        "health_endpoint": "/health",
        "tools_endpoint": "/mcp/tools",
        "call_endpoint": "/mcp/call",
    },
    "social": {
        "base_url": settings.SOCIAL_MCP_URL.replace("/score", ""),
        "score_endpoint": "/score",
        "health_endpoint": "/health",
        "tools_endpoint": "/mcp/tools",
        "call_endpoint": "/mcp/call",
    },
}


async def call_mcp_tool(
    server_name: str,
    tool_name: str,
    arguments: dict,
) -> dict:
    """
    Call an MCP tool on a specific server via the /mcp/call endpoint.
    Returns the tool result or an error dict.
    """
    server = MCP_SERVERS.get(server_name)
    if not server:
        return {"status": "error", "error": f"Unknown MCP server: {server_name}"}

    url = server["base_url"] + server["call_endpoint"]
    payload = {"name": tool_name, "arguments": arguments}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return {"status": "ok", "data": response.json()}
    except Exception as e:
        log.error(f"MCP call failed: server={server_name} tool={tool_name} error={e}")
        return {"status": "error", "error": str(e)}


async def get_mcp_tools(server_name: str) -> dict:
    """List available tools from an MCP server."""
    server = MCP_SERVERS.get(server_name)
    if not server:
        return {"status": "error", "error": f"Unknown MCP server: {server_name}"}

    url = server["base_url"] + server["tools_endpoint"]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            response.raise_for_status()
            return {"status": "ok", "tools": response.json().get("tools", [])}
    except Exception as e:
        log.error(f"Failed to list MCP tools: {server_name} error={e}")
        return {"status": "error", "error": str(e)}


async def check_mcp_health() -> dict:
    """Check health of all MCP servers."""
    results = {}
    for name, server in MCP_SERVERS.items():
        url = server["base_url"] + server["health_endpoint"]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                results[name] = "ok" if response.status_code == 200 else "error"
        except Exception:
            results[name] = "unreachable"
    return results
