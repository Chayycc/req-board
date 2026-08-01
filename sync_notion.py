#!/usr/bin/env python3
"""Pull the Notion "Tally requirement" DB (Data Request + Issue) and merge into
the Supabase board row (id='req'), preserving board-managed edits.

Runs on a schedule (GitHub Actions, every 10 min). Direction: Notion -> board.
Board-managed fields (status/stage/owner/prio/deadline/note) are NEVER overwritten
for existing rows; descriptive fields are refreshed; date fields are backfilled
only when empty; brand-new Notion rows are added.

Env:
  NOTION_TOKEN   Notion internal integration secret (required)
"""
import json, os, re, sys, time, urllib.request, urllib.error

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"
DB_ID = "817d901464a84f24bffe480ed2158983"
CATEGORIES = ["ต้องการขอ Data Request ", "แจ้งปัญหารายงาน/การใช้งานข้อมูล"]

# Supabase (anon key is public — same as the board page)
SB_URL = "https://rticsujbdozqmjyiohvm.supabase.co"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6"
          "InJ0aWNzdWpiZG96cW1qeWlvaHZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ4OTg0Nzks"
          "ImV4cCI6MjEwMDQ3NDQ3OX0.sXpsoHkXh8Exwb4Ep2H25PuVLNrw7GUlJNcnyzPb6hk")
BOARD_ID = "req"

CAT_MAP = {"ต้องการขอ Data Request ": "Data Request",
           "ต้องการขอ Data Request": "Data Request",
           "แจ้งปัญหารายงาน/การใช้งานข้อมูล": "Data Issue"}
LEGACY = {"Pending": "Review", "Cancel": "Cancelled", "Task Approved": "Req Approved",
          "Approved": "Req Approved", "UAT": "Review"}
STATUSES = {"Not started", "Review", "Req Approved", "In progress", "On Hold", "Blocked", "Done", "Cancelled"}
PRIOS = {"Urgent", "High", "Medium", "Low"}
# board-managed: keep on existing rows. refreshed: overwrite from Notion. date: backfill if empty.
REFRESH = ["name", "type", "dept", "deptShort", "company", "output", "title", "desc",
           "worklink", "formlink", "category", "submitted", "url"]
BACKFILL = ["startDate", "completed", "actualDate"]


def http(method, url, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode() or "null")


# ---------- Notion property extractors ----------
def p_title(p):
    return "".join(t.get("plain_text", "") for t in (p or {}).get("title", [])).strip()


def p_text(p):
    return "".join(t.get("plain_text", "") for t in (p or {}).get("rich_text", [])).strip()


def p_select(p):
    s = (p or {}).get("select")
    return s.get("name", "") if s else ""


def p_status(p):
    s = (p or {}).get("status")
    return s.get("name", "") if s else ""


def p_date(p):
    d = (p or {}).get("date")
    if not d or not d.get("start"):
        return ""
    return d["start"].split("T")[0]


def p_url(p):
    return (p or {}).get("url") or ""


def norm_prio(v):
    head = re.split(r"[:：]", v or "")[0].strip()
    head = head.split()[0] if head else ""
    return head if head in PRIOS else ""


def norm_status(v):
    v = (v or "").strip()
    v = LEGACY.get(v, v)
    return v if v in STATUSES else "Not started"


# board Status/Priority (short) -> Notion option names (for push board -> Notion)
STATUS_TO_NOTION = {"Not started": "Not started", "Review": "In progress", "Req Approved": "In progress",
                    "In progress": "In progress", "On Hold": "Pending", "Blocked": "Pending",
                    "Done": "Done", "Cancelled": "Cancel"}
PRIO_TO_NOTION = {"Urgent": "Urgent : กระทบการดำเนินงานทันที / เสี่ยงเกิดความเสียหาย",
                  "High": "High : กระทบการตัดสินใจ/งานเร่งด่วน",
                  "Medium": "Medium : กระทบบางส่วนของงาน", "Low": "Low : ไม่กระทบการทำงาน"}
RAW = {}  # id -> raw Notion values, used to push only genuinely-changed fields


def notion_to_req(page):
    pr = page.get("properties", {})
    dept = p_select(pr.get("Request by Dep."))
    title = p_title(pr.get("Request by Name"))
    st = norm_status(p_status(pr.get("Status")))
    ptitle = p_text(pr.get("Project Title"))
    wdesc = p_text(pr.get("Work description"))
    pid = page["id"].replace("-", "")
    RAW[pid] = {"status": p_status(pr.get("Status")), "priority": p_select(pr.get("Priority")),
                "Deadline": p_date(pr.get("Deadline")), "Start Date": p_date(pr.get("Start Date")),
                "Complete Date": p_date(pr.get("Complete Date")), "Actual Date": p_date(pr.get("Actual Date")),
                "note": p_text(pr.get("Note (รายละเอียด)"))}
    return {
        "id": pid,
        "url": "https://www.notion.so/" + pid,
        "name": title or "(ไม่ระบุชื่อ)",
        "status": st,
        "stage": "queue" if st == "Not started" else "board",
        "prio": norm_prio(p_select(pr.get("Priority"))),
        "type": p_select(pr.get("ประเภทของงาน Request")),
        "dept": dept,
        "deptShort": re.split(r"[:：]", dept)[0].strip() if dept else "",
        "company": p_select(pr.get("เครือบริษัท")),
        "output": p_select(pr.get("Output Type")),
        "title": ptitle or wdesc or "(ไม่มีหัวข้อ)",
        "desc": wdesc,
        "note": p_text(pr.get("Note (รายละเอียด)")),
        "worklink": p_url(pr.get("Link งานที่ทำ")),
        "formlink": p_url(pr.get("Link ที่แนบจาก request form")),
        "category": CAT_MAP.get(p_select(pr.get("เรื่องที่ต้องการ Data")), "Data Request"),
        "deadline": p_date(pr.get("Deadline")),
        "startDate": p_date(pr.get("Start Date")),
        "completed": p_date(pr.get("Complete Date")),
        "actualDate": p_date(pr.get("Actual Date")),
        "submitted": p_date(pr.get("Submitted date")),
        "created": page.get("created_time", ""),
        "owner": "",
    }


def fetch_notion():
    headers = {"Authorization": "Bearer " + NOTION_TOKEN, "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    flt = {"or": [{"property": "เรื่องที่ต้องการ Data", "select": {"equals": c}} for c in CATEGORIES]}
    out, cursor = [], None
    while True:
        body = {"filter": flt, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        _, res = http("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", headers, body)
        out.extend(notion_to_req(pg) for pg in res.get("results", []))
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break
    return out


def load_board():
    _, rows = http("GET", f"{SB_URL}/rest/v1/board?id=eq.{BOARD_ID}&select=data",
                   {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY})
    if rows and rows[0].get("data") and isinstance(rows[0]["data"].get("reqs"), list):
        return rows[0]["data"]["reqs"]
    return []


def save_board(reqs):
    from datetime import datetime, timezone
    body = [{"id": BOARD_ID, "data": {"reqs": reqs}, "updated_at": datetime.now(timezone.utc).isoformat()}]
    headers = {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    http("POST", f"{SB_URL}/rest/v1/board?on_conflict=id", headers, body)


def push_to_notion(board):
    """Push board-managed fields (status/priority/dates/note) back to Notion,
    but only for items whose value actually differs from Notion right now."""
    headers = {"Authorization": "Bearer " + NOTION_TOKEN, "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    pushed, CAP = 0, 80
    for r in board:
        raw = RAW.get(r["id"])
        if raw is None:
            continue  # not in the current Notion result set
        props = {}
        tgt_status = STATUS_TO_NOTION.get(r.get("status", ""), r.get("status", ""))
        if tgt_status and tgt_status != raw["status"]:
            props["Status"] = {"status": {"name": tgt_status}}
        if r.get("prio"):
            tgt_prio = PRIO_TO_NOTION.get(r["prio"], r["prio"])
            if tgt_prio != raw["priority"]:
                props["Priority"] = {"select": {"name": tgt_prio}}
        for bkey, nkey in (("deadline", "Deadline"), ("startDate", "Start Date"),
                           ("completed", "Complete Date"), ("actualDate", "Actual Date")):
            bv = r.get(bkey, "") or ""
            if bv != (raw[nkey] or ""):
                props[nkey] = {"date": {"start": bv}} if bv else {"date": None}
        bnote = r.get("note", "") or ""
        if bnote != (raw["note"] or ""):
            props["Note (รายละเอียด)"] = {"rich_text": [{"text": {"content": bnote[:1900]}}] if bnote else []}
        if not props:
            continue
        try:
            http("PATCH", f"https://api.notion.com/v1/pages/{r['id']}", headers, {"properties": props})
            pushed += 1
        except urllib.error.HTTPError as e:
            print(f"  push {r['id']} failed: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  push {r['id']} err: {e}", file=sys.stderr)
        time.sleep(0.34)  # stay under Notion's ~3 req/s limit
        if pushed >= CAP:
            print(f"  push cap {CAP} reached — rest syncs next run", file=sys.stderr)
            break
    return pushed


def main():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    fresh = fetch_notion()
    board = load_board()
    by_id = {r["id"]: r for r in board}
    added = updated = 0
    for s in fresh:
        e = by_id.get(s["id"])
        if not e:
            by_id[s["id"]] = s
            added += 1
            continue
        changed = False
        for k in REFRESH:
            if s.get(k) and e.get(k) != s[k]:
                e[k] = s[k]; changed = True
        for k in BACKFILL:
            if not e.get(k) and s.get(k):
                e[k] = s[k]; changed = True
        if changed:
            updated += 1
    merged = list(by_id.values())
    save_board(merged)
    pushed = push_to_notion(merged)
    print(f"pull: {len(fresh)} notion | +{added} new | ~{updated} refreshed | total {len(merged)} || push: {pushed} -> notion")


if __name__ == "__main__":
    main()
