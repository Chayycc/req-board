// Supabase Edge Function: notion-sync
// Writes board edits back to the Notion "Tally requirement" database.
// The board POSTs { id: <32-hex Notion page id>, fields: {...} } and this
// function PATCHes the corresponding Notion page. The Notion integration
// token is read from the NOTION_TOKEN secret (never exposed to the browser).
//
// Deploy:
//   supabase functions deploy notion-sync --project-ref rticsujbdozqmjyiohvm --no-verify-jwt
//   supabase secrets set NOTION_TOKEN=secret_xxx --project-ref rticsujbdozqmjyiohvm

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";

const NOTION_TOKEN = Deno.env.get("NOTION_TOKEN") ?? "";
const NOTION_VERSION = "2022-06-28";

// board Priority (short) -> Notion "Priority" select option (full label)
const PRIO_MAP: Record<string, string> = {
  "Urgent": "Urgent : กระทบการดำเนินงานทันที / เสี่ยงเกิดความเสียหาย",
  "High": "High : กระทบการตัดสินใจ/งานเร่งด่วน",
  "Medium": "Medium : กระทบบางส่วนของงาน",
  "Low": "Low : ไม่กระทบการทำงาน",
};

// board Status (8) -> Notion "Status" (existing 5). Notion API cannot create
// new status options, so extra board statuses map to the nearest Notion one.
// If you add Review / Req Approved / On Hold / Blocked / Cancelled as options in
// the Notion Status field, switch this to a pass-through (name === board value).
const STATUS_MAP: Record<string, string> = {
  "Not started": "Not started",
  "Review": "In progress",
  "Req Approved": "In progress",
  "In progress": "In progress",
  "On Hold": "Pending",
  "Blocked": "Pending",
  "Done": "Done",
  "Cancelled": "Cancel",
};

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function buildProps(f: Record<string, unknown>) {
  const p: Record<string, unknown> = {};
  if (typeof f.status === "string" && f.status) {
    p["Status"] = { status: { name: STATUS_MAP[f.status] ?? f.status } };
  }
  if (f.priority !== undefined) {
    p["Priority"] = f.priority
      ? { select: { name: PRIO_MAP[f.priority as string] ?? f.priority } }
      : { select: null };
  }
  const dateField = (key: string, notionName: string) => {
    if (f[key] !== undefined) {
      p[notionName] = f[key] ? { date: { start: f[key] } } : { date: null };
    }
  };
  dateField("deadline", "Deadline");
  dateField("startDate", "Start Date");
  dateField("completeDate", "Complete Date");
  dateField("actualDate", "Actual Date");
  if (f.note !== undefined) {
    const note = String(f.note ?? "");
    p["Note (รายละเอียด)"] = {
      rich_text: note ? [{ text: { content: note.slice(0, 1900) } }] : [],
    };
  }
  return p;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "method" }, 405);
  if (!NOTION_TOKEN) return json({ error: "NOTION_TOKEN not set" }, 500);

  let payload: { id?: string; fields?: Record<string, unknown> };
  try {
    payload = await req.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const id = (payload.id ?? "").replace(/-/g, "");
  if (!/^[0-9a-fA-F]{32}$/.test(id)) return json({ error: "bad id" }, 400);

  const props = buildProps(payload.fields ?? {});
  if (!Object.keys(props).length) return json({ error: "no fields" }, 400);

  const res = await fetch(`https://api.notion.com/v1/pages/${id}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${NOTION_TOKEN}`,
      "Notion-Version": NOTION_VERSION,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ properties: props }),
  });
  const text = await res.text();
  return json({ ok: res.ok, status: res.status, notion: res.ok ? undefined : text }, res.ok ? 200 : 502);
});
