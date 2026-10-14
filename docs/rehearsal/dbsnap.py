"""Read-only DB digest: per table row count + per-row/per-column md5 (no values printed). Usage: snap <dsn> <out.json> | diff <a.json> <b.json>"""
import asyncio, hashlib, json, sys
import asyncpg

async def snap(dsn, out):
    c = await asyncpg.connect(dsn)
    tabs = [r["tablename"] for r in await c.fetch("select tablename from pg_tables where schemaname='public' and tablename<>'alembic_version' order by 1")]
    res = {"_rev": [r[0] for r in await c.fetch("select version_num from alembic_version")], "tables": {}}
    for t in tabs:
        cols = [r["column_name"] for r in await c.fetch("select column_name from information_schema.columns where table_schema='public' and table_name=$1 order by ordinal_position", t)]
        pk = "id" if "id" in cols else None
        rows = await c.fetch(f'select * from "{t}"')
        d = {}
        for i, r in enumerate(rows):
            key = str(r[pk]) if pk else str(i)
            d[key] = {k: hashlib.md5(json.dumps(r[k], default=str, sort_keys=True).encode()).hexdigest()[:10] for k in cols}
        res["tables"][t] = {"count": len(rows), "cols": cols, "pk": bool(pk), "rows": d}
    json.dump(res, open(out, "w"))
    print(f"snap {out}: rev={res['_rev']} tables={len(tabs)} rows={sum(v['count'] for v in res['tables'].values())}")

def diff(a, b):
    A, B = json.load(open(a)), json.load(open(b))
    print("revisions:", A["_rev"], "->", B["_rev"])
    for t in sorted(set(A["tables"]) | set(B["tables"])):
        if t not in A["tables"]: print(f"  NEW TABLE {t}: {B['tables'][t]['count']} rows"); continue
        if t not in B["tables"]: print(f"  DROPPED TABLE {t}: {A['tables'][t]['count']} rows"); continue
        x, y = A["tables"][t], B["tables"][t]
        msgs = []
        if x["count"] != y["count"]: msgs.append(f"count {x['count']} -> {y['count']}")
        added = [c for c in y["cols"] if c not in x["cols"]]; removed = [c for c in x["cols"] if c not in y["cols"]]
        if added: msgs.append("new cols " + ",".join(added))
        if removed: msgs.append("REMOVED cols " + ",".join(removed))
        if x["pk"]:
            gone = [k for k in x["rows"] if k not in y["rows"]]
            if gone: msgs.append(f"{len(gone)} rows MISSING after")
            for c in x["cols"]:
                if c in y["cols"]:
                    n = sum(1 for k, r in x["rows"].items() if k in y["rows"] and y["rows"][k].get(c) != r[c])
                    if n: msgs.append(f"col {c}: {n} rows changed")
        if msgs: print(f"  {t}: " + "; ".join(msgs))
if __name__ == "__main__":
    if sys.argv[1] == "snap": asyncio.run(snap(sys.argv[2], sys.argv[3]))
    else: diff(sys.argv[2], sys.argv[3])
