#!/usr/bin/env python3
"""Transform Notion 'Tally requirement' export batches -> req-board seed (data.js).
Reads /tmp/req_b0.json, req_b1.json, req_b2.json (JSON arrays of raw rows),
dedupes by id, normalizes, writes req-board/data.js as `window.REQ_SEED = [...]`."""
import json, os, re, sys

BATCHES = ["/tmp/req_b0.json", "/tmp/req_b1.json", "/tmp/req_b2.json"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.js")

CAT_MAP = {
    "ต้องการขอ Data Request ": "Data Request",
    "ต้องการขอ Data Request": "Data Request",
    "แจ้งปัญหารายงาน/การใช้งานข้อมูล": "Data Issue",
}
STATUSES = {"Not started", "Pending", "In progress", "Done", "Cancel"}


def norm_prio(p):
    if not p:
        return ""
    head = re.split(r"[:：]", p)[0].strip()
    head = head.split()[0] if head else ""
    m = {"Urgent": "Urgent", "High": "High", "Medium": "Medium", "Low": "Low"}
    return m.get(head, "")


def norm_status(s):
    s = (s or "").strip()
    return s if s in STATUSES else "Not started"


def pid(url):
    if not url:
        return ""
    seg = url.rstrip("/").split("/")[-1]
    seg = seg.split("?")[0]
    return seg.replace("-", "")


def clean(v):
    if v is None:
        return ""
    return str(v).strip()


def date_only(v):
    v = clean(v)
    if not v:
        return ""
    return v.split(" ")[0].split("T")[0]


rows = []
for f in BATCHES:
    if not os.path.exists(f):
        print(f"WARN missing {f}", file=sys.stderr)
        continue
    data = json.load(open(f, encoding="utf-8"))
    if isinstance(data, dict) and "results" in data:
        data = data["results"]
    rows.extend(data)

seen = {}
for r in rows:
    i = pid(r.get("url"))
    if not i:
        continue
    dept = clean(r.get("dept"))
    obj = {
        "id": i,
        "url": clean(r.get("url")),
        "name": clean(r.get("name")) or "(ไม่ระบุชื่อ)",
        "status": norm_status(r.get("status")),
        "prio": norm_prio(r.get("prio")),
        "type": clean(r.get("rtype")),
        "dept": dept,
        "deptShort": re.split(r"[:：]", dept)[0].strip() if dept else "",
        "company": clean(r.get("company")),
        "output": clean(r.get("output")),
        "title": clean(r.get("ptitle")) or clean(r.get("wdesc")),
        "desc": clean(r.get("wdesc")),
        "note": clean(r.get("note")),
        "worklink": clean(r.get("worklink")),
        "formlink": clean(r.get("formlink")),
        "category": CAT_MAP.get(clean(r.get("category")), "Data Request"),
        "deadline": date_only(r.get("deadline")),
        "submitted": date_only(r.get("submitted")),
        "completed": date_only(r.get("completed")),
        "created": clean(r.get("createdTime")),
        "owner": "",
    }
    # dedupe: keep the one with richer content (longer created wins ~ same)
    seen[i] = obj

out = sorted(seen.values(), key=lambda x: x["created"], reverse=True)
js = "window.REQ_SEED = " + json.dumps(out, ensure_ascii=False, indent=0).replace("\n", "") + ";\n"
open(OUT, "w", encoding="utf-8").write(js)

# stats
from collections import Counter
cs = Counter(o["status"] for o in out)
cc = Counter(o["category"] for o in out)
print(f"rows in: {len(rows)}  unique: {len(out)}")
print("status:", dict(cs))
print("category:", dict(cc))
print("wrote:", OUT)
