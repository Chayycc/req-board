# Prioritization Board : Task

บอร์ดจัดคิวงาน **Data Request / Data Issue** สำหรับทีม Data — clone จาก [prio-board](https://chayycc.github.io/prio-board/) แต่ปรับให้แก้สถานะในบอร์ดได้เอง ไม่ต้องเด้งไปหน้า Notion

**Live:** https://chayycc.github.io/req-board/

## ฟีเจอร์
- **Task Queue** — งานเข้าใหม่ (status `Not started`) มากองด้านบน กด **รับงาน** เพื่อกำหนดผู้รับ + ย้ายลงบอร์ด
- **Kanban** — แบ่งตาม Status / Priority · ลากการ์ดข้ามคอลัมน์เพื่อเปลี่ยนสถานะ
- **Drawer** — คลิกการ์ดเพื่อดู/แก้ Status · Priority · Owner · Deadline · Note (ไม่เด้งไป Notion)
- Filter: ประเภท · priority · แผนก · เครือบริษัท · owner + ค้นหา
- ธีมสว่าง/มืด · sync สถานะเรียลไทม์

## สถาปัตยกรรม
```
Notion "Tally requirement" DB ──(seed ครั้งเดียว)──▶ data.js
                                                       │
data.js (window.REQ_SEED) ──▶ Supabase (row id='req') ◀──▶ index.html
                              แก้ในบอร์ด → เขียนกลับ Supabase (source of truth)
```
- **Storage:** Supabase table `board`, row `id='req'` (แชร์ project เดียวกับ prio-board)
- **Seed:** `data.js` = snapshot จาก Notion (Data Request + Issue) — แก้ในบอร์ดไม่กระทบ Notion
- ตอนโหลด ระบบ merge งานใหม่จาก `data.js` เข้ามาอัตโนมัติ (ไม่ทับ status/owner ที่แก้ไว้)

## รีเฟรชข้อมูลจาก Notion
เมื่อมี request ใหม่ใน Notion และอยากดึงเข้าบอร์ด:
1. รัน query ดึง Notion ใหม่ → เขียนทับ `/tmp/req_b*.json`
2. `python3 build_seed.py` → สร้าง `data.js` ใหม่
3. commit + push → กด **↻ Sync** ในบอร์ด (หรือ reload) เพื่อ merge งานใหม่

## ไฟล์
| ไฟล์ | หน้าที่ |
|---|---|
| `index.html` | ตัวแอปทั้งหมด (self-contained) |
| `data.js` | seed `window.REQ_SEED` จาก Notion |
| `build_seed.py` | แปลง Notion export → `data.js` |
