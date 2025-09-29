**Run local (stdio):**


```bash
pip install -r requirements.txt
export MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=...
python server.py # defaults to stdio if MCP_TRANSPORT=stdio
```


**Run remote (HTTP/SSE):**


```bash
export MCP_TRANSPORT=sse PORT=8000 HOST=0.0.0.0
python server.py
```


**Tools available:** `ping`, `list_databases`, `list_tables(database?)`, `describe_table(table, database?)`, `run_sql(sql, database?)`, `create_database(name)`, `drop_database(name)`, `create_table(ddl_sql, database?)`, `drop_table(table, database?)`, `insert_row(table, data, database?)`, `execute_many(sql, params, database?)`


**Auth:** If `API_KEY` is set, send header `Authorization: Bearer <API_KEY>` when connecting.