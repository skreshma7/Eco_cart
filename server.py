#!/usr/bin/env python3
"""Eco-Friendly Shopping Assistant - backend.

Zero dependencies: Python standard library only (sqlite3 + http.server).
Run:  python3 server.py   then open  http://localhost:8000
"""
import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "eco.db"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# Score A (best) .. F (worst). Higher rank = greener. NULL rank = no eco-data.
RANK = {"A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    brand      TEXT NOT NULL,
    category   TEXT NOT NULL,
    price      REAL NOT NULL CHECK (price >= 0),
    score      TEXT CHECK (score IN ('A','B','C','D','E','F')),
    eco_rank   INTEGER,          -- A=6 ... F=1, NULL = no eco-data (flagged)
    co2_kg     REAL,
    materials  TEXT,
    certs      TEXT
);
-- Composite index so eco-score + price + category filters stay fast.
CREATE INDEX IF NOT EXISTS idx_filter ON products (category, eco_rank, price);
CREATE INDEX IF NOT EXISTS idx_rank_price ON products (eco_rank, price);
"""


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        items = json.loads((BASE / "products.json").read_text())
        db.executemany(
            "INSERT INTO products (id,name,brand,category,price,score,eco_rank,co2_kg,materials,certs)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(p["id"], p["name"], p["brand"], p["category"], p["price"], p["score"],
              RANK.get(p["score"]), p["co2"], p["materials"], p["certs"]) for p in items],
        )
        db.commit()
    db.close()


SORTS = {
    "eco": "eco_rank IS NULL, eco_rank DESC, price ASC",
    "price_asc": "price ASC",
    "price_desc": "price DESC",
    "name": "name COLLATE NOCASE ASC",
}


def query_products(qs):
    where, args = [], []
    cats = [c for c in qs.get("category", [""])[0].split(",") if c]
    if cats:
        where.append("category IN (%s)" % ",".join("?" * len(cats)))
        args += cats
    if qs.get("max_price", [""])[0]:
        where.append("price <= ?")
        args.append(float(qs["max_price"][0]))
    if qs.get("min_price", [""])[0]:
        where.append("price >= ?")
        args.append(float(qs["min_price"][0]))
    min_score = qs.get("min_score", [""])[0]
    if min_score in RANK:
        where.append("eco_rank >= ?")  # NULL rows are excluded automatically
        args.append(RANK[min_score])
    if qs.get("hide_unrated", ["0"])[0] == "1":
        where.append("eco_rank IS NOT NULL")
    q = qs.get("q", [""])[0].strip()
    if q:
        where.append("(name LIKE ? OR brand LIKE ? OR materials LIKE ?)")
        args += [f"%{q}%"] * 3
    sql = "SELECT * FROM products"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + SORTS.get(qs.get("sort", ["eco"])[0], SORTS["eco"])
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(sql, args)]
    cats_all = [r[0] for r in db.execute("SELECT DISTINCT category FROM products ORDER BY 1")]
    db.close()
    for r in rows:
        r["co2"] = r.pop("co2_kg")
        r.pop("eco_rank")
    return {"products": rows, "categories": cats_all}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/products":
            try:
                data = query_products(parse_qs(url.query))
                self._send(200, json.dumps(data).encode(), "application/json")
            except ValueError:
                self._send(400, b'{"error":"bad parameter"}', "application/json")
        elif url.path in ("/", "/index.html"):
            self._send(200, (BASE / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    init_db()
    print(f"Eco Shopping Assistant running at http://localhost:{PORT}  (Ctrl+C to stop)")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
