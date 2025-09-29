# ─────────────────────────────────────────────────────────────────────────────
# File: server.py
# Run: python server.py
# Env (set in Render): MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE (optional),
#                      MCP_TRANSPORT=sse, PORT=8000, API_KEY=<strong-random>
# Notes: Exposes full read/write MySQL controls via MCP tools over SSE (HTTP).
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
import mysql.connector
from mysql.connector import errorcode

# ASGI bits for HTTP/SSE
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
import uvicorn

# ---------------------- Config ----------------------
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DEFAULT_DB = os.getenv("MYSQL_DATABASE")  # optional default schema

API_KEY = os.getenv("API_KEY")  # optional bearer token; if set, required

TRANSPORT = os.getenv("MCP_TRANSPORT", "http").lower()  # stdio | http | sse
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

# ---------------------- MCP Init ----------------------
mcp = FastMCP("mysql-mcp")

# ---------------------- Helpers ----------------------

def _connect(database: Optional[str] = None):
    cfg = dict(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        autocommit=True,
        database=database or DEFAULT_DB,
        auth_plugin=os.getenv("MYSQL_AUTH_PLUGIN", None) or "mysql_native_password",
    )
    return mysql.connector.connect(**cfg)

async def _require_auth(ctx) -> None:
    """Require Authorization: Bearer <API_KEY> if API_KEY is configured."""
    if not API_KEY:
        return
    token = None
    try:
        # FastMCP exposes request headers on HTTP/SSE transports via context
        headers = (getattr(ctx, "request_headers", None)
                   or getattr(getattr(ctx, "request_context", None), "request", None) and getattr(ctx.request_context.request, "headers", {}))
        if headers:
            token = headers.get("authorization") or headers.get("Authorization")
    except Exception:
        token = None
    if not token or not token.lower().startswith("bearer ") or token.split(" ", 1)[1].strip() != API_KEY:
        raise PermissionError("Unauthorized: missing or invalid bearer token")

# ---------------------- Tools ----------------------

@mcp.tool()
async def ping(ctx) -> str:
    await _require_auth(ctx)
    return "pong"

@mcp.tool()
async def list_databases(ctx) -> List[str]:
    """List all databases (schemas)."""
    await _require_auth(ctx)
    con = _connect(None)
    cur = con.cursor()
    cur.execute("SHOW DATABASES")
    dbs = [r[0] for r in cur.fetchall()]
    cur.close(); con.close()
    return dbs

@mcp.tool()
async def list_tables(ctx, database: Optional[str] = None) -> List[str]:
    """List tables in the given database (or default)."""
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor()
    cur.execute("SHOW TABLES")
    tables = [r[0] for r in cur.fetchall()]
    cur.close(); con.close()
    return tables

@mcp.tool()
async def describe_table(ctx, table: str, database: Optional[str] = None) -> List[Dict[str, Any]]:
    """Describe a table's columns and types."""
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor(dictionary=True)
    cur.execute("DESCRIBE `%s`" % table.replace("`", ""))  # basic escaping of backticks
    rows = cur.fetchall()
    cur.close(); con.close()
    return rows

@mcp.tool()
async def run_sql(ctx, sql: str, database: Optional[str] = None) -> Dict[str, Any]:
    """Run arbitrary SQL (DDL/DML/SELECT). Returns {rows, rowcount, lastrowid}."""
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor(dictionary=True)
    try:
        cur.execute(sql)
        result: Dict[str, Any] = {
            "rowcount": cur.rowcount,
            "lastrowid": getattr(cur, "lastrowid", None),
        }
        try:
            data = cur.fetchall()
            result["rows"] = data
        except mysql.connector.errors.InterfaceError:
            # no result set
            result["rows"] = []
        return result
    finally:
        try:
            cur.close(); con.close()
        except Exception:
            pass

@mcp.tool()
async def create_database(ctx, name: str) -> str:
    await _require_auth(ctx)
    con = _connect(None)
    cur = con.cursor()
    cur.execute(f"CREATE DATABASE `{name.replace('`','')}`")
    cur.close(); con.close()
    return f"created database {name}"

@mcp.tool()
async def drop_database(ctx, name: str) -> str:
    await _require_auth(ctx)
    con = _connect(None)
    cur = con.cursor()
    cur.execute(f"DROP DATABASE `{name.replace('`','')}`")
    cur.close(); con.close()
    return f"dropped database {name}"

@mcp.tool()
async def create_table(ctx, ddl_sql: str, database: Optional[str] = None) -> str:
    """Run a CREATE TABLE ... statement verbatim."""
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor()
    cur.execute(ddl_sql)
    cur.close(); con.close()
    return "table created"

@mcp.tool()
async def drop_table(ctx, table: str, database: Optional[str] = None) -> str:
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor()
    cur.execute(f"DROP TABLE `{table.replace('`','')}`")
    cur.close(); con.close()
    return f"dropped table {table}"

@mcp.tool()
async def insert_row(ctx, table: str, data: Dict[str, Any], database: Optional[str] = None) -> Dict[str, Any]:
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor()
    cols = ", ".join(f"`{c.replace('`','')}`" for c in data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    sql = f"INSERT INTO `{table.replace('`','')}` ({cols}) VALUES ({placeholders})"
    cur.execute(sql, list(data.values()))
    last_id = cur.lastrowid
    cur.close(); con.close()
    return {"lastrowid": last_id}

@mcp.tool()
async def execute_many(ctx, sql: str, params: List[List[Any]], database: Optional[str] = None) -> Dict[str, Any]:
    """Execute parametrized statement many times (e.g., INSERT/UPDATE)."""
    await _require_auth(ctx)
    con = _connect(database)
    cur = con.cursor()
    cur.executemany(sql, params)
    rc = cur.rowcount
    cur.close(); con.close()
    return {"rowcount": rc}

# ---------------------- ASGI App for HTTP/SSE ----------------------

async def _health(_request):
    return PlainTextResponse("OK")

def build_asgi_app():
    if TRANSPORT == "http":
        mounted = mcp.streamable_http_app()  # MCP endpoint at /mcp when mounted at root
        routes = [
            Route("/health", _health),
            Mount("/", app=mounted),
        ]
    elif TRANSPORT == "sse":
        mounted = mcp.sse_app()
        routes = [
            Route("/health", _health),
            Mount("/", app=mounted),
        ]
    else:
        routes = [Route("/health", _health)]
    return Starlette(routes=routes)

# ---------------------- Entrypoint ----------------------
if __name__ == "__main__":
    if TRANSPORT == "stdio":
        mcp.run()
    else:
        app = build_asgi_app()
        uvicorn.run(app, host=HOST, port=PORT)
