// GET  /api/records?status=1                 ->  {enabled}
// GET  /api/records?collection=outcomes      ->  {docs: {id: record}}
// POST /api/records  {collection, id, data}  ->  {ok: true}
//
// Shared storage for investigator outcomes, analyst decisions and intake decisions, kept in
// Redis through its REST API. Works with Vercel's Upstash Redis integration
// (KV_REST_API_URL / KV_REST_API_TOKEN) or a direct Upstash database
// (UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN). Without either, pages save in the browser.
const COLLECTIONS = new Set(["outcomes", "decisions", "intake"]);
const ID = /^[A-Za-z0-9_-]{1,40}$/;
const MAX_RECORD_BYTES = 16000;

function config() {
  const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  return url && token ? { url, token } : null;
}

async function redis(cfg, command) {
  const r = await fetch(cfg.url, {
    method: "POST",
    headers: { authorization: `Bearer ${cfg.token}`, "content-type": "application/json" },
    body: JSON.stringify(command),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok || body.error) throw new Error(body.error || `Redis returned ${r.status}`);
  return body.result;
}

export default async function handler(req, res) {
  const cfg = config();

  if (req.method === "GET") {
    if (req.query.status !== undefined) return res.status(200).json({ enabled: Boolean(cfg) });
    if (!cfg) return res.status(503).json({ error: "Shared storage is not configured." });
    const collection = String(req.query.collection || "");
    if (!COLLECTIONS.has(collection)) return res.status(400).json({ error: "Unknown collection." });
    const flat = (await redis(cfg, ["HGETALL", `prime:${collection}`])) || [];
    const docs = {};
    for (let i = 0; i + 1 < flat.length; i += 2) {
      try { docs[flat[i]] = JSON.parse(flat[i + 1]); } catch (e) {}
    }
    res.setHeader("Cache-Control", "no-store");
    return res.status(200).json({ docs });
  }

  if (req.method === "POST") {
    if (!cfg) return res.status(503).json({ error: "Shared storage is not configured." });
    const { collection, id, data } = req.body || {};
    if (!COLLECTIONS.has(collection) || !ID.test(String(id || ""))) {
      return res.status(400).json({ error: "Send a known collection and an id of letters, digits, - or _." });
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) return res.status(400).json({ error: "Send the record as an object." });
    const value = JSON.stringify(data);
    if (value.length > MAX_RECORD_BYTES) return res.status(413).json({ error: "Record too large." });
    await redis(cfg, ["HSET", `prime:${collection}`, id, value]);
    return res.status(200).json({ ok: true });
  }

  res.setHeader("Allow", "GET, POST");
  return res.status(405).json({ error: "Use GET or POST." });
}
