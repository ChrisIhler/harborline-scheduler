// Cloudflare Worker for the Harbor Line demo.
//
//   GET  /             the demo page (web/index.html from GitHub, pinned to one commit)
//   GET  /api/status   {live: true|false}: is the Claude endpoint switched on?
//   POST /api/propose  {request} -> {ops, questions}: Claude proposes edits (never times
//                      it can't quote). The browser still runs the grounding check and
//                      the engine, so a bad proposal is rejected there.
//
// Settings (Worker > Settings > Variables and Secrets):
//   ANTHROPIC_API_KEY  secret. Leave unset and the demo runs in example-only mode.
//   SRC_COMMIT         git commit the page and Python files are served from.
//   DAILY_LIMIT        live requests per UTC day, all visitors together (default 50).
//   PER_IP_LIMIT       live requests per UTC day per visitor (default 10).
//   MODEL              Claude model id (default claude-haiku-5-5).
// Binding: LIMITS (KV namespace) for the counters.

const REPO = "ChrisIhler/harborline-scheduler";

const SYSTEM = [
  "You turn a water-taxi scheduler's plain-English request into edit operations for the",
  "Harbor Line Water Taxi (a fictional network). You never write a timetable.",
  "",
  "Rules:",
  "1. Never invent a time or a number. Every clock time and minute count in an operation must be",
  "   written in the request. If one is missing, return no op for it and ask a question instead.",
  "2. Every op has \"quote\": words copied exactly from the request that justify it.",
  "3. Times are 24-hour \"HH:MM\". Days: weekday, saturday, sunday, all.",
  "4. If the request is not about this schedule, return no ops and one short question.",
  "",
  "Operations:",
  "- set_service_hours {day, start?, end?}",
  "- set_headway {day, start, end, minutes}        (\"every 15 minutes from 11 am to 4 pm\")",
  "- close_dock {day, dock, start, end}            (only RIVERWALK or MARKET; terminals can't close)",
  "- add_departure {day, time} / cancel_departure {day, time}   (departures from UNION)",
  "- add_vessel {day, vessel} / remove_vessel {day, vessel}",
  "- add_dock {dock_id, name, after, minutes_from_prev, minutes_to_next, dwell_min?, berths?}",
  "",
  "Network:",
  "- Docks in route order: UNION (Union Station Landing), RIVERWALK (Riverwalk Plaza),",
  "  MARKET (Market Street), LIGHTHOUSE (Lighthouse Pier). Boats run UNION -> LIGHTHOUSE and back.",
  "- Fleet: HERON, KESTREL, OSPREY, PLOVER, TERN, WREN.",
  "- Rostered: weekday HERON KESTREL OSPREY PLOVER TERN; saturday all six; sunday HERON KESTREL OSPREY PLOVER.",
].join("\n");

const TOOL = {
  name: "propose_edits",
  description: "Propose schedule edit operations. Each op must quote the request.",
  input_schema: {
    type: "object",
    properties: {
      ops: {
        type: "array",
        items: {
          type: "object",
          properties: {
            op: { type: "string", enum: ["set_service_hours", "set_headway", "close_dock", "add_departure",
              "cancel_departure", "add_vessel", "remove_vessel", "add_dock"] },
            quote: { type: "string" }, day: { type: "string", enum: ["weekday", "saturday", "sunday", "all"] },
            start: { type: "string" }, end: { type: "string" }, time: { type: "string" },
            minutes: { type: "integer" }, dock: { type: "string" }, vessel: { type: "string" },
            dock_id: { type: "string" }, name: { type: "string" }, after: { type: "string" },
            minutes_from_prev: { type: "integer" }, minutes_to_next: { type: "integer" },
            dwell_min: { type: "integer" }, berths: { type: "integer" },
          },
          required: ["op", "quote"],
        },
      },
      questions: { type: "array", items: { type: "string" } },
    },
    required: ["ops", "questions"],
  },
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", "cache-control": "no-store" } });

async function page(env, ctx) {
  const commit = env.SRC_COMMIT || "main";
  const src = "https://cdn.jsdelivr.net/gh/" + REPO + "@" + commit + "/";
  const cache = caches.default;
  const key = new Request("https://harborline.cache/page/" + commit);
  let html = await (await cache.match(key))?.text();
  if (!html) {
    const r = await fetch(src + "web/index.html");
    if (!r.ok) return new Response("Demo page unavailable right now.", { status: 502 });
    html = (await r.text()).replace("<head>", "<head>\n<script>window.HARBORLINE_SRC=" + JSON.stringify(src) + "</script>");
    ctx.waitUntil(cache.put(key, new Response(html, { headers: { "cache-control": "max-age=3600" } })));
  }
  return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=300" } });
}

async function overLimit(env, ip) {
  if (!env.LIMITS) return "Live Claude is not configured.";
  const day = new Date().toISOString().slice(0, 10);
  const dayKey = "day:" + day, ipKey = "ip:" + day + ":" + ip;
  const [total, mine] = await Promise.all([env.LIMITS.get(dayKey), env.LIMITS.get(ipKey)]);
  const dayLimit = parseInt(env.DAILY_LIMIT || "50", 10), ipLimit = parseInt(env.PER_IP_LIMIT || "10", 10);
  if ((+total || 0) >= dayLimit) return "Today's live Claude requests are used up. The examples still work, and it resets at midnight UTC.";
  if ((+mine || 0) >= ipLimit) return "You've used your " + ipLimit + " live requests for today. The examples still work.";
  await Promise.all([
    env.LIMITS.put(dayKey, String((+total || 0) + 1), { expirationTtl: 172800 }),
    env.LIMITS.put(ipKey, String((+mine || 0) + 1), { expirationTtl: 172800 }),
  ]);
  return null;
}

async function propose(request, env) {
  if (!env.ANTHROPIC_API_KEY) return json({ error: "Live Claude is off right now." }, 503);
  let body;
  try { body = await request.json(); } catch { return json({ error: "Send JSON: {\"request\": \"...\"}" }, 400); }
  const text = String(body?.request || "").trim();
  if (!text) return json({ error: "Type a request first." }, 400);
  if (text.length > 400) return json({ error: "Please keep the request under 400 characters." }, 400);
  const limited = await overLimit(env, request.headers.get("cf-connecting-ip") || "unknown");
  if (limited) return json({ error: limited }, 429);

  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({
      model: env.MODEL || "claude-haiku-5-5",
      max_tokens: 800,
      system: SYSTEM,
      tools: [TOOL],
      tool_choice: { type: "tool", name: "propose_edits" },
      messages: [{ role: "user", content: text }],
    }),
  });
  if (!r.ok) return json({ error: "Claude is unavailable right now. The examples still work." }, 502);
  const data = await r.json();
  const use = (data.content || []).find(b => b.type === "tool_use");
  if (!use) return json({ error: "Claude didn't return edits. Try rewording the request." }, 502);
  return json({ ops: use.input.ops || [], questions: use.input.questions || [] });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/api/status") return json({ live: Boolean(env.ANTHROPIC_API_KEY && env.LIMITS) });
    if (url.pathname === "/api/propose") {
      if (request.method !== "POST") return json({ error: "POST only" }, 405);
      return propose(request, env);
    }
    if (url.pathname === "/" || url.pathname === "/index.html") return page(env, ctx);
    return new Response("Not found", { status: 404 });
  },
};
