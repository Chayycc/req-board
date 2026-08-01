# KM — Prioritization Board : Task

Knowledge base ของ req-board: สถาปัตยกรรม · data model · decisions · การ sync Notion · ops

---

## 1. ภาพรวม

บอร์ดจัดคิว **Data Request / Data Issue** ให้ทีม Data (11 คน) จัดการ status/owner ในบอร์ดได้เอง แทนการเด้งไปหน้า Notion แล้ว sync กลับ Notion อัตโนมัติ

**ที่มาปัญหาเดิม:** dashboard เก่า (Team Project Monitoring) ผูก `onclick="window.open(notion.so/...)"` ทุกแถว → กดปรับอะไรก็เด้งไป Notion ต้องไปปิด status เองใน Notion

## 2. 3 โซน (flow)

```
📥 Task Queue (งานใหม่ ยังไม่รับ, stage=queue)
      ↓ กด "รับงาน" / ลากลงบอร์ด
🗂️ งานที่รับแล้ว (stage=board, คอลัมน์ = status)
      ↓ ลากลงกล่องล่าง = ปิดงาน
✅ เสร็จแล้ว — แยกตามฝ่าย (status=Done, คอลัมน์ = ฝ่าย)
```

- **stage** = concept ของบอร์ด (queue|board) — Notion ไม่มี · Queue = ยังไม่กดรับ
- **status (8):** Not started · Review · Req Approved · In progress · On Hold · Blocked · Done · Cancelled
- งานที่รับแล้ว: คอลัมน์ = 6 active + Cancelled (Done ไปกล่องเสร็จแล้ว)

## 3. Data model (Supabase `board.data.reqs[]`)

```
{ id (32-hex Notion), url, name (ผู้ขอ), status, stage, prio (Urgent/High/Medium/Low),
  type, dept, deptShort, company, output, title, desc, note, worklink, formlink,
  category (Data Request|Data Issue), deadline, startDate, completed, actualDate,
  submitted, created, owner (nickname 1 ใน 11), comments:[{by,text,at}] }
```

- **workflow fields** (บอร์ดคุม): status, stage, owner, prio, deadline, startDate, completed, actualDate, comments/note
- **descriptive** (Notion คุม, pull มา refresh): name, type, dept, company, output, title, desc, worklink, formlink, category, submitted

## 4. Notion sync (`sync_notion.py`, GitHub Actions cron 10 นาที)

### Pull (Notion → board)
- query DB filter category ∈ {Data Request, Data Issue} · map property → req shape
- งานใหม่ → add · งานเดิม → refresh descriptive + backfill date/owner **ถ้าบอร์ดว่าง** (ไม่ทับที่แก้)

### Push (board → Notion, เฉพาะ field ที่ต่างจริง)
| board | → Notion property | map |
|---|---|---|
| status | Status (status type) | 8→5: Review/Req Approved→In progress, On Hold/Blocked→Pending, Cancelled→Cancel |
| prio | Priority (select) | สั้น→เต็ม ("High : กระทบ...") |
| deadline/startDate/completed/actualDate | Deadline / Start Date / Complete Date / Actual Date | date |
| note (=flatten comments) | Note (รายละเอียด) | rich_text |
| owner | Project Owner (person) | nickname → user id (`OWNER_TO_NOTION`) |

### Owner mapping (11)
- forward `OWNER_TO_NOTION`: nickname → Notion user id (push)
- reverse `NOTION_TO_OWNER`: user id → nickname (pull backfill) · **Patiwat 2 account** (`fb6f5ef3`/`156d872b`) → Tar (push ใช้ `fb6f5ef3`)
- owner ที่ไม่ใช่ 11 คน (requester/คนนอก) → บอร์ดเว้นว่าง, ไม่แตะ Notion

### กัน overwrite
- push owner เฉพาะ owner **ไม่ว่าง + map ได้ + ต่างจาก Notion** → ไม่ล้าง owner เดิมของงานที่บอร์ดเว้นว่าง

## 5. Decisions (resolve แล้ว)

| # | เลือก | เหตุผล |
|---|---|---|
| Storage | Supabase (ไม่เขียน Notion จากหน้า static ตรงๆ) | token หลุด + CORS |
| โครง board | รวม Task Priority เข้าเป็น status board เดียว | Notion track แค่ status |
| Queue | stage-based (ยังไม่กดรับ) ไม่ใช่ status-based | flow "รับงาน" |
| Sync engine | GitHub Actions cron (ไม่ใช่ Supabase edge function) | ไม่ต้อง Supabase CLI/login · secret ที่เดียว |
| Owner sync | person field (option 1) + บอร์ด authoritative | ให้ตรงกับ owner บอร์ด |
| Cancelled | แสดงคอลัมน์ตลอด (เอา toggle ออก) | กันข้อมูลหาย |
| ปี filter | โชว์ พ.ศ. | ตรง dropdown |
| Comment | thread + tag ผู้เขียน (พิมพ์เลือกชื่อ ไม่มี login) | ทีมคอมเมนต์กันง่าย |

## 6. ฟีเจอร์เด่น

- drag ข้ามโซน · drawer แก้ status/prio/owner/deadline/Start/Complete/Actual date + **comment thread** (tag ทีม + เวลา)
- filter: category/priority/dept/company/owner/**ปี(พ.ศ.)/เดือน(multi-select)** + search
- **Planning page** (Capacity/Workload): งานที่แต่ละคนถือ + status breakdown + workload bar + overdue/done
- **เสร็จแล้ว calculator:** นับ Done ตาม filter ปี/เดือน + scope tag
- โลโก้ Easy Money + favicon · ปุ่ม **"ขอ Req"** → Tally form (`tally.so/r/nG9gLZ`)

## 7. Ops / วิธีดูแล

- **แก้โค้ด:** `git add . && git commit && git push` → Pages rebuild ~1 นาที
- **รัน sync มือ:** `gh workflow run notion-sync.yml --repo Chayycc/req-board`
- **ดูผล sync:** `gh run view <id> --repo Chayycc/req-board --log | grep -E "pull:|push:"` → `pull: N notion | +X new | ~Y refreshed | ... || push: Z -> notion`
- **เพิ่ม owner:** เพิ่มใน `OWNERS` (index.html) + `OWNER_TO_NOTION` (sync_notion.py) → commit + run workflow
- **token:** GitHub repo secret `NOTION_TOKEN` (ผู้ใช้ตั้งเอง) · Notion integration ต้องแชร์ DB "Tally requirement"

## 8. Verified (2026-08-01)

- count 262 = 262 (Notion = board) · status/priority/owner ตรง (Ohm round-trip, Tar→Patiwat push+restore สำเร็จ)
- owner backfill: บอร์ดมี owner 257/262 (จากเดิม 2) map เป็น 11 ชื่อ
