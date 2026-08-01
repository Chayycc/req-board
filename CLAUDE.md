# CLAUDE.md — Prioritization Board : Task (req-board)

Context สำหรับ Claude session ที่มาทำงานกับโปรเจกต์นี้ต่อ อ่านก่อนเริ่มทุกครั้ง

---

## คืออะไร

บอร์ดจัดคิวงาน **Data Request / Data Issue** ของทีม Data — clone มาจาก [prio-board](https://chayycc.github.io/prio-board/) แต่ปรับให้แก้ status/owner ในบอร์ดได้เอง **ไม่ต้องเด้งไปหน้า Notion** และ **sync 2 ทางกับ Notion อัตโนมัติทุก 10 นาที**

- **Live:** https://chayycc.github.io/req-board/
- **Repo:** github.com/Chayycc/req-board (GitHub Pages, public)
- **Source ข้อมูล:** Notion DB "Tally requirement" (Tally form → Notion) · database id `817d901464a84f24bffe480ed2158983` · data source `collection://69d08b83-b7dc-4d23-a83a-965914f9dc91`

## ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `index.html` | ตัวแอปทั้งหมด (self-contained, no-build) |
| `data.js` | seed `window.REQ_SEED` (snapshot จาก Notion) — ใช้ตอน Supabase ว่างเท่านั้น |
| `build_seed.py` | แปลง Notion export (`/tmp/req_b*.json`) → `data.js` |
| `sync_notion.py` | **หัวใจ sync 2 ทาง** Notion ⇄ Supabase (รันโดย GitHub Actions) |
| `.github/workflows/notion-sync.yml` | cron ทุก 10 นาที + workflow_dispatch |
| `supabase/functions/notion-sync/index.ts` | edge function push real-time (ปิดอยู่ `NOTION_SYNC=false` — cron ทำแทน) |
| `KM.md` | คู่มือสถาปัตยกรรม + decisions + ops |

## สถาปัตยกรรม

```
Notion "Tally requirement"  ──(GitHub Actions cron 10 นาที: sync_notion.py)──▶  Supabase board row id='req'  ◀──▶  index.html (GitHub Pages)
        ▲                                pull: งานใหม่ + descriptive fields
        └───── push: status/priority/dates/note/owner ที่แก้ในบอร์ด ────────────
```

- **Supabase:** project `rticsujbdozqmjyiohvm` · table `board` · row `id='req'` (data jsonb = `{reqs:[...]}`) · anon key ฝัง client (public)
- **แหล่งความจริง:** บอร์ดคุม **workflow fields** (status/stage/owner/prio/deadline/dates/comments) · Notion คุม **descriptive** (name/dept/company/title/desc/type)

## กฎสำคัญตอนแก้

1. **แก้ `index.html` แล้ว** → commit + push → GitHub Pages rebuild ~1 นาที (บางที browser cache: เปิด `?v=N`)
2. **แก้ owner mapping** → แก้ `OWNER_TO_NOTION` ใน `sync_notion.py` (reverse map สร้างอัตโนมัติ)
3. **owner ในบอร์ด (nickname)** ต้องอยู่ในลิสต์ `OWNERS` (index.html) + map ใน `sync_notion.py` ถึงจะ sync Notion
4. **ห้ามจับ Notion token** — ผู้ใช้ตั้งเองใน GitHub repo secret `NOTION_TOKEN` (Settings → Secrets → Actions)
5. **status บอร์ด 8 ตัว** → Notion มี 5 → `sync_notion.py` map ให้ (Review/Req Approved→In progress, On Hold/Blocked→Pending); ถ้าอยากตรงเป๊ะต้องเพิ่ม option ใน Notion เอง
6. เทสต์ push/pull: `gh workflow run notion-sync.yml` แล้วดู log `gh run view <id> --log | grep -E "pull:|push:"`

## Owner mapping (11 คน)

`OWNER_TO_NOTION` ใน `sync_notion.py`: Chay · Shay(=Sivatep) · Tar(=Patiwat, 2 account→Tar) · Ohm · Toto · Fahsai · Mew · Sine · Bow · Ploy · Ako — owner ที่ไม่อยู่ 10+1 คน = บอร์ดเว้นว่าง

## Open items

- ⚠️ **Notion token หลุดในแชท 2 ครั้ง** — ควร regenerate + อัปเดต GitHub secret
- Supabase anon key public (รับได้ เหมือน prio-board)
- concurrency last-write-wins (poll 15 วิ ข้ามตอน drawer เปิด/มี save ค้าง — ลดโอกาสแล้ว)
- Notion status มีแค่ 5 → บอร์ด 8 collapse ตอน push
- real-time push ปิด (ใช้ cron 10 นาที); edge function พร้อม deploy ถ้าอยาก instant
- แก้คอมเมนต์เดิมไม่ได้ (ลบ+เพิ่มใหม่)
