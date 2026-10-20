// POST /api/extract  {email, received}  ->  {result: {field: {value, confidence}}}
// GET  /api/extract                     ->  {enabled}
//
// Reads a first-notice-of-loss email with Claude. The prompt lives here, not in the browser,
// so the API key can only be used for this one job. Needs ANTHROPIC_API_KEY; the model can be
// changed with ANTHROPIC_MODEL.
import Anthropic from "@anthropic-ai/sdk";

const PERILS = ["Collision", "Theft", "Windscreen", "Third-party injury", "Water damage", "Fire", "Burglary", "Storm"];
const DOCUMENTS = [
  "photos of the damage", "repair estimate", "other driver's details", "police report", "both sets of keys",
  "photo of the windscreen", "other party's details", "medical report", "plumber's report", "fire service report",
  "list of damaged items", "list of stolen items", "proof of ownership",
];
const MAX_EMAIL_CHARS = 8000;

function buildPrompt(email, received) {
  return `You read first-notice-of-loss emails for an insurer. Extract the fields below from the email and return ONLY a JSON object.
Each field is {"value": ..., "confidence": number from 0 to 1}. Use null when the email does not say. Do not guess a value the email does not support; lower the confidence when you infer.
Fields:
- policy_number: format P followed by 6 digits (pad a shorter number with zeros, e.g. "policy number 211" -> "P000211")
- claimant_name: the sender's full name
- loss_date: ISO date YYYY-MM-DD.${received ? ` The email was received on ${received}; resolve relative dates like "last Wednesday" against that date.` : ""}
- peril: exactly one of ${PERILS.join(", ")}
- location: street and town as written
- amount_claimed: a number, no currency symbol; null if no amount is given
- police_report: true if the email says it was reported to the police
- documents: array of attached documents, lowercased, using these names where they fit: ${DOCUMENTS.join(", ")}

Email:
"""
${email}
"""`;
}

// Tolerant JSON read: whole reply, else a fenced block, else first { to last }
function parseJson(text) {
  const tries = [text, (text.match(/```(?:json)?\s*([\s\S]*?)```/) || [])[1], text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1)];
  for (const t of tries) {
    if (!t) continue;
    try { return JSON.parse(t); } catch (e) {}
  }
  return null;
}

export default async function handler(req, res) {
  const enabled = Boolean(process.env.ANTHROPIC_API_KEY);
  if (req.method === "GET") return res.status(200).json({ enabled });
  if (req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    return res.status(405).json({ error: "Use GET or POST." });
  }
  if (!enabled) return res.status(503).json({ error: "Reading with Claude is off: set ANTHROPIC_API_KEY." });

  const { email, received } = req.body || {};
  if (typeof email !== "string" || !email.trim() || email.length > MAX_EMAIL_CHARS) {
    return res.status(400).json({ error: `Send the email text as "email" (up to ${MAX_EMAIL_CHARS} characters).` });
  }
  if (received != null && !/^\d{4}-\d{2}-\d{2}$/.test(String(received))) {
    return res.status(400).json({ error: 'Send "received" as YYYY-MM-DD.' });
  }

  const client = new Anthropic();
  try {
    const response = await client.beta.messages.create({
      model: process.env.ANTHROPIC_MODEL || "claude-opus-5-5",
      max_tokens: 16000,
      output_config: { effort: "low" }, // a short extraction; raise if accuracy needs it
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      messages: [{ role: "user", content: buildPrompt(email, received) }],
    });
    if (response.stop_reason === "refusal") {
      return res.status(422).json({ error: "Claude declined to read this email." });
    }
    const text = response.content.filter(b => b.type === "text").map(b => b.text).join("");
    const result = parseJson(text);
    if (!result || typeof result !== "object") return res.status(502).json({ error: "Claude's reply was not valid JSON." });
    return res.status(200).json({ result, model: response.model });
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) return res.status(429).json({ error: "Rate limited; try again shortly." });
    if (error instanceof Anthropic.AuthenticationError) return res.status(503).json({ error: "The Anthropic API key was rejected." });
    if (error instanceof Anthropic.BadRequestError) return res.status(502).json({ error: error.message });
    if (error instanceof Anthropic.APIError) return res.status(502).json({ error: `Anthropic API error ${error.status}.` });
    throw error;
  }
}
