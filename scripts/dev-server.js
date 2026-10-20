// Local server without the Vercel CLI: serves public/ and runs api/*.js the way Vercel does.
//   node scripts/dev-server.js            (port 3000, or PORT=...)
// Reads .env from the project root if present, so ANTHROPIC_API_KEY and the Redis variables work locally.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const PUBLIC = join(ROOT, "public");
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

if (existsSync(join(ROOT, ".env"))) {
  for (const line of readFileSync(join(ROOT, ".env"), "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && m[2] && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}

function vercelRes(res) {
  res.status = code => { res.statusCode = code; return res; };
  res.json = obj => { res.setHeader("content-type", "application/json"); res.end(JSON.stringify(obj)); return res; };
  return res;
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString("utf8");
  try { return raw ? JSON.parse(raw) : undefined; } catch (e) { return raw; }
}

createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  try {
    if (url.pathname.startsWith("/api/")) {
      const name = url.pathname.slice(5).replace(/[^a-z0-9_-]/gi, "");
      const file = join(ROOT, "api", name + ".js");
      if (!existsSync(file)) { res.statusCode = 404; return res.end("Not found"); }
      const { default: handler } = await import(pathToFileURL(file).href);
      req.query = Object.fromEntries(url.searchParams);
      req.body = await readBody(req);
      return await handler(req, vercelRes(res));
    }
    let path = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, "");
    if (path.endsWith("/")) path += "index.html";
    const file = join(PUBLIC, path);
    if (!file.startsWith(PUBLIC) || !(await stat(file).catch(() => null))?.isFile()) { res.statusCode = 404; return res.end("Not found"); }
    res.setHeader("content-type", TYPES[extname(file)] || "application/octet-stream");
    res.end(await readFile(file));
  } catch (e) {
    console.error(e);
    if (!res.headersSent) res.statusCode = 500;
    res.end("Server error");
  }
}).listen(process.env.PORT || 3000, () => console.log(`Prime Insurance AI on http://localhost:${process.env.PORT || 3000}`));
