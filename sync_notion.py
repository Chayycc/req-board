#!/usr/bin/env python3
"""Bidirectional sync between Notion and the Supabase board rows.

Two independent board datasets are synced each run:
  • main     — Notion "Tally requirement" (Data Request + Issue)  ->  row id='req'
  • internal — Notion "Data_Internal Request"                     ->  row id='req-internal'

Direction per dataset: pull (Notion -> board) + push (board -> Notion).
Board-managed fields (status/stage/owner/prio/deadline/note) are NEVER overwritten
for existing rows; descriptive fields are refreshed; date fields are backfilled
only when empty; brand-new Notion rows are added. Runs on GitHub Actions (10 min).

Env:
  NOTION_TOKEN   Notion internal integration secret (required, must have access to BOTH DBs)
"""
import json, os, re, sys, time, urllib.request, urllib.error

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_VERSION = "2022-06-28"

# ----- main DB (Tally requirement) -----
DB_ID = "817d901464a84f24bffe480ed2158983"
CATEGORIES = ["ต้องการขอ Data Request ", "แจ้งปัญหารายงาน/การใช้งานข้อมูล"]
CAT_MAP = {"ต้องการขอ Data Request ": "Data Request",
           "ต้องการขอ Data Request": "Data Request",
           "แจ้งปัญหารายงาน/การใช้งานข้อมูล": "Data Issue"}

# ----- internal DB (Data_Internal Request) -----
INT_DB_ID = "2b68fd87ee6e804f88f8f252850ed099"
# Member Assign (Thai nickname select) -> board nickname. Fallback owner when Project Owner (person) is empty.
MEMBER_TO_OWNER = {"เอโกะ": "Ako", "ฟ้าใส": "Fahsai", "โอม": "Ohm",
                   "โตโต้": "Toto", "หมิว": "Mew", "เช่": "Shay"}

# Supabase (anon key is public — same as the board page)
SB_URL = "https://rticsujbdozqmjyiohvm.supabase.co"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6"
          "InJ0aWNzdWpiZG96cW1qeWlvaHZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ4OTg0Nzks"
          "ImV4cCI6MjEwMDQ3NDQ3OX0.sXpsoHkXh8Exwb4Ep2H25PuVLNrw7GUlJNcnyzPb6hk")

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


def p_people(p):
    return [u.get("id", "") for u in (p or {}).get("people", [])]


def norm_prio(v):
    head = re.split(r"[:：]", v or "")[0].strip()
    head = head.split()[0] if head else ""
    return head if head in PRIOS else ""


def norm_status(v):
    v = (v or "").strip()
    v = LEGACY.get(v, v)
    return v if v in STATUSES else "Not started"


# board owner (nickname) -> Notion user id (person field "Project Owner"). Shared by both DBs.
# Unmapped/empty owners are never pushed (board-only).
OWNER_TO_NOTION = {
    "Chay": "3f5a2fb4-57d1-4202-8a64-cd815201a268",   # Chay
    "Shay": "63a73367-6806-45d5-805e-08c752ee875b",   # Sivatep Petcharat
    "Tar": "fb6f5ef3-02c4-4139-a25c-298fc41696d5",    # Patiwat Kunpijit
    "Ohm": "67833646-7266-43ba-a9eb-c40dfe441945",    # Ohm
    "Toto": "a0a161ee-b691-4b15-9f06-fcefbbe8c71e",   # worapop wiboonsirichai
    "Fahsai": "1b2d872b-594c-812d-9dcf-0002fcbb4441", # Rattanaporn Chaipanya
    "Mew": "054f9bd7-c494-41d4-b995-3cfb6f3d8c5e",    # Nutcha Suteesukprasert
    "Sine": "55e1a95e-0c89-423c-beeb-c448deb9ebd2",   # Sureeporn Sukaram
    "Bow": "74704f1f-ad55-4531-9b66-d14a7e28c86b",    # Kanya Meekaew
    "Ako": "1a0d872b-594c-8111-a55a-00025fc247d3",    # Ako Pakawadee
    "Ploy": "9c4284c9-ad55-4ac3-89cb-6ecc40cf9c06",   # Ploy M
}
# reverse: Notion user id -> board nickname (pull owner Notion -> board).
# IDs not listed here (external/requester) resolve to "" = board stays blank.
NOTION_TO_OWNER = {v: k for k, v in OWNER_TO_NOTION.items()}
NOTION_TO_OWNER["156d872b-594c-811c-88dd-00026eedf78e"] = "Tar"  # 2nd Patiwat Kunpijit account -> Tar (canonical fb6f5ef3 on push)

# board Status/Priority (short) -> Notion option names (for push board -> Notion)
STATUS_TO_NOTION = {"Not started": "Not started", "Review": "In progress", "Req Approved": "In progress",
                    "In progress": "In progress", "On Hold": "Pending", "Blocked": "Pending",
                    "Done": "Done", "Cancelled": "Cancel"}
PRIO_TO_NOTION = {"Urgent": "Urgent : กระทบการดำเนินงานทันที / เสี่ยงเกิดความเสียหาย",
                  "High": "High : กระทบการตัดสินใจ/งานเร่งด่วน",
                  "Medium": "Medium : กระทบบางส่วนของงาน", "Low": "Low : ไม่กระทบการทำงาน"}
# internal DB has only 4 statuses (Not started/Pending/In progress/Done) and plain priority options.
# Cancelled has no home in the internal DB -> None = skip pushing status.
INT_STATUS_TO_NOTION = {"Not started": "Not started", "Review": "In progress", "Req Approved": "In progress",
                        "In progress": "In progress", "On Hold": "Pending", "Blocked": "Pending",
                        "Done": "Done", "Cancelled": None}
INT_PRIO_TO_NOTION = {"Urgent": "Urgent", "High": "High", "Medium": "Medium", "Low": "Low"}

RAW = {}  # id -> raw Notion values, used to push only genuinely-changed fields


def notion_to_req_main(page):
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
                "note": p_text(pr.get("Note (รายละเอียด)")), "people": p_people(pr.get("Project Owner"))}
    owner = next((NOTION_TO_OWNER[u] for u in RAW[pid]["people"] if u in NOTION_TO_OWNER), "")
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
        "owner": owner,
    }


def notion_to_req_internal(page):
    pr = page.get("properties", {})
    st = norm_status(p_status(pr.get("Status")))
    ptitle = p_title(pr.get("Project Title"))
    detail = p_text(pr.get("Project/Task Detail"))
    company = p_select(pr.get("เครือบริษัท"))
    submitter = p_select(pr.get("Submitted by"))
    pid = page["id"].replace("-", "")
    RAW[pid] = {"status": p_status(pr.get("Status")), "priority": p_select(pr.get("Priority ")),
                "Due dates ": p_date(pr.get("Due dates ")), "Start Date": p_date(pr.get("Start Date")),
                "Complete Date": p_date(pr.get("Complete Date")),
                "note": "", "people": p_people(pr.get("Project Owner"))}
    # owner: Project Owner (person) first, then Member Assign (Thai nickname) fallback
    owner = next((NOTION_TO_OWNER[u] for u in RAW[pid]["people"] if u in NOTION_TO_OWNER), "")
    if not owner:
        owner = MEMBER_TO_OWNER.get(p_select(pr.get("Member Assign")), "")
    return {
        "id": pid,
        "url": "https://www.notion.so/" + pid,
        "name": submitter or "(ไม่ระบุชื่อ)",
        "status": st,
        "stage": "queue" if st == "Not started" else "board",
        "prio": norm_prio(p_select(pr.get("Priority "))),
        "type": p_select(pr.get("Type of work ")),
        "dept": company,          # internal has no department — group by company chain instead
        "deptShort": company,
        "company": company,
        "output": "",
        "title": ptitle or detail or "(ไม่มีหัวข้อ)",
        "desc": detail,
        "note": "",
        "worklink": p_url(pr.get("Online Link")),
        "formlink": "",
        "category": "",           # internal has no Data Request/Issue category
        "deadline": p_date(pr.get("Due dates ")),
        "startDate": p_date(pr.get("Start Date")),
        "completed": p_date(pr.get("Complete Date")),
        "actualDate": "",         # internal DB has no Actual Date field
        "submitted": "",          # no submitted-date field; created_time drives year/month filter
        "created": page.get("created_time", ""),
        "owner": owner,
    }


# ---------- per-dataset config ----------
CONFIGS = [
    {"name": "main", "db": DB_ID, "board_id": "req",
     "filter": {"or": [{"property": "เรื่องที่ต้องการ Data", "select": {"equals": c}} for c in CATEGORIES]},
     "to_req": notion_to_req_main,
     "status_prop": "Status", "prio_prop": "Priority",
     "status_map": STATUS_TO_NOTION, "prio_map": PRIO_TO_NOTION,
     "date_fields": [("deadline", "Deadline"), ("startDate", "Start Date"),
                     ("completed", "Complete Date"), ("actualDate", "Actual Date")],
     "note_prop": "Note (รายละเอียด)"},
    {"name": "internal", "db": INT_DB_ID, "board_id": "req-internal",
     "filter": None,
     "to_req": notion_to_req_internal,
     "status_prop": "Status", "prio_prop": "Priority ",
     "status_map": INT_STATUS_TO_NOTION, "prio_map": INT_PRIO_TO_NOTION,
     "date_fields": [("deadline", "Due dates "), ("startDate", "Start Date"),
                     ("completed", "Complete Date")],
     "note_prop": None},
]


def fetch(cfg):
    headers = {"Authorization": "Bearer " + NOTION_TOKEN, "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    out, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cfg["filter"]:
            body["filter"] = cfg["filter"]
        if cursor:
            body["start_cursor"] = cursor
        _, res = http("POST", f"https://api.notion.com/v1/databases/{cfg['db']}/query", headers, body)
        out.extend(cfg["to_req"](pg) for pg in res.get("results", []))
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break
    return out


def load_board(board_id):
    _, rows = http("GET", f"{SB_URL}/rest/v1/board?id=eq.{board_id}&select=data",
                   {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY})
    if rows and rows[0].get("data") and isinstance(rows[0]["data"].get("reqs"), list):
        return rows[0]["data"]["reqs"]
    return []


def save_board(board_id, reqs):
    from datetime import datetime, timezone
    body = [{"id": board_id, "data": {"reqs": reqs}, "updated_at": datetime.now(timezone.utc).isoformat()}]
    headers = {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    http("POST", f"{SB_URL}/rest/v1/board?on_conflict=id", headers, body)


def push_to_notion(cfg, board):
    """Push board-managed fields back to Notion, only where the value actually differs."""
    headers = {"Authorization": "Bearer " + NOTION_TOKEN, "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    smap, pmap = cfg["status_map"], cfg["prio_map"]
    pushed, CAP = 0, 80
    for r in board:
        raw = RAW.get(r["id"])
        if raw is None:
            continue  # not in the current Notion result set
        props = {}
        tgt_status = smap.get(r.get("status", ""), r.get("status", ""))
        if tgt_status and tgt_status != raw["status"]:
            props[cfg["status_prop"]] = {"status": {"name": tgt_status}}
        if r.get("prio"):
            tgt_prio = pmap.get(r["prio"], r["prio"])
            if tgt_prio and tgt_prio != raw["priority"]:
                props[cfg["prio_prop"]] = {"select": {"name": tgt_prio}}
        for bkey, nkey in cfg["date_fields"]:
            bv = r.get(bkey, "") or ""
            if bv != (raw.get(nkey) or ""):
                props[nkey] = {"date": {"start": bv}} if bv else {"date": None}
        if cfg["note_prop"]:
            bnote = r.get("note", "") or ""
            if bnote != (raw.get("note") or ""):
                props[cfg["note_prop"]] = {"rich_text": [{"text": {"content": bnote[:1900]}}] if bnote else []}
        own = r.get("owner", "")
        uid = OWNER_TO_NOTION.get(own)
        if own and uid and raw.get("people") != [uid]:  # only push mapped, non-empty, changed owner
            props["Project Owner"] = {"people": [{"id": uid}]}
        if not props:
            continue
        try:
            http("PATCH", f"https://api.notion.com/v1/pages/{r['id']}", headers, {"properties": props})
            pushed += 1
        except urllib.error.HTTPError as e:
            print(f"  [{cfg['name']}] push {r['id']} failed: {e.code} {e.read().decode()[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"  [{cfg['name']}] push {r['id']} err: {e}", file=sys.stderr)
        time.sleep(0.34)  # stay under Notion's ~3 req/s limit
        if pushed >= CAP:
            print(f"  [{cfg['name']}] push cap {CAP} reached — rest syncs next run", file=sys.stderr)
            break
    return pushed


def sync_one(cfg):
    fresh = fetch(cfg)
    board = load_board(cfg["board_id"])
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
        if not e.get("owner") and s.get("owner"):  # board empty -> adopt Notion owner; once set, board wins
            e["owner"] = s["owner"]; changed = True
        if changed:
            updated += 1
    merged = list(by_id.values())
    save_board(cfg["board_id"], merged)
    pushed = push_to_notion(cfg, merged)
    print(f"[{cfg['name']}] pull: {len(fresh)} notion | +{added} new | ~{updated} refreshed "
          f"| total {len(merged)} || push: {pushed} -> notion")


def main():
    if not NOTION_TOKEN:
        print("ERROR: NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    for cfg in CONFIGS:
        try:
            sync_one(cfg)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:300]
            except Exception:
                pass
            print(f"[{cfg['name']}] SYNC FAILED: {e.code} {body}", file=sys.stderr)
        except Exception as e:
            print(f"[{cfg['name']}] SYNC FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
