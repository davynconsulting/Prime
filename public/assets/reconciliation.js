(function () {
const DATA = window.__PRIME_DATA;
const LINES = DATA.lines, ITEMS = DATA.items;
// Analyst order: fraud events, then suggested matches (strongest first), then lines with no match
const rank = l => l.event ? 0 : l.items.length ? 1 : 2;
LINES.sort((a, b) => rank(a) - rank(b) || b.confidence - a.confidence || a.date.localeCompare(b.date));
const BY_ID = new Map(LINES.map(l => [l.line_id, l]));
const DECISIONS = { accept: "Accepted", reject: "Rejected" };
let decisions = {}, db = null, myId = null, saving = false;
let filter = "open", query = "", selected = null, threshold = 0.9;

const $ = id => document.getElementById(id);
const money = n => (n < 0 ? "−" : "") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const isAuto = l => l.confidence >= threshold && !l.event;
const confBand = c => c >= 0.9 ? "low" : c >= 0.7 ? "mid" : "high";  // low risk = grey, weak = red

function summary() {
  const auto = LINES.filter(isAuto).length;
  const exc = LINES.length - auto;
  const decided = Object.keys(decisions).filter(id => !isAuto(BY_ID.get(id) || {})).length;
  $("s-lines").textContent = LINES.length.toLocaleString();
  $("s-auto").textContent = Math.round(auto / LINES.length * 100) + "%";
  $("s-auto-l").textContent = `cleared automatically (${auto.toLocaleString()} lines, ${LINES.filter(l => isAuto(l) && !l.correct).length} wrong)`;
  $("s-exc").textContent = exc - decided;
  $("s-exc-l").textContent = `exceptions left for an analyst (${decided} decided)`;
  $("s-ev").textContent = LINES.filter(l => l.event).length;
}

function visible() {
  const q = query.trim().toLowerCase();
  return LINES.filter(l => {
    const auto = isAuto(l), done = !!decisions[l.line_id];
    if (filter === "open" && (auto || done)) return false;
    if (filter === "events" && !l.event) return false;
    if (filter === "done" && !done) return false;
    if (filter === "auto" && !auto) return false;
    if (!q) return true;
    return [l.counterparty, l.narrative, l.line_id, String(l.amount)].some(v => String(v).toLowerCase().includes(q));
  });
}

function renderList() {
  const rows = visible();
  if (!rows.length) { $("list").innerHTML = `<p class="note" style="padding:16px">${filter === "open" ? "Every exception has a decision." : "No lines match."}</p>`; return; }
  $("list").innerHTML = rows.slice(0, 300).map(l => {
    const d = decisions[l.line_id];
    const tag = d ? `<span class="state ${d.decision === "accept" ? "st-notfraud" : "st-confirmed"}">${DECISIONS[d.decision]}</span>`
      : l.event ? `<span class="state st-confirmed">Fraud event</span>` : isAuto(l) ? `<span class="state st-open">Auto</span>` : `<span class="state st-inconclusive">${esc(l.kind)}</span>`;
    return `<button class="row" role="listitem" data-id="${l.line_id}" aria-current="${l.line_id === selected}">
      <div class="conf s-${confBand(l.confidence)} num">${Math.round(l.confidence * 100)}</div>
      <div class="who"><div>${esc(l.counterparty)}</div>
        <div class="muted" style="font-size:12.5px"><span class="num ${l.amount > 0 ? "amt-in" : "amt-out"}">${money(l.amount)}</span> · ${l.date.slice(5)} · ${esc(l.narrative)}</div></div>
      ${tag}</button>`;
  }).join("");
}

function renderCase() {
  const el = $("case"), l = BY_ID.get(selected);
  if (!l) { el.innerHTML = `<p class="muted">Pick a bank line to see its proposed match.</p>`; return; }
  const d = decisions[l.line_id];
  const its = l.items.map(id => ({ id, ...ITEMS[id] }));
  const total = its.reduce((s, i) => s + i.amount, 0);
  el.innerHTML = `
    <div class="casehead">
      <div style="display:grid;gap:4px;min-width:0">
        <h2>${esc(l.counterparty)}</h2>
        <span class="muted"><span class="mono">${l.line_id}</span> · ${l.account} · ${l.date}</span>
      </div>
      <div class="bigscore"><b class="num ${l.amount > 0 ? "amt-in" : ""}">${money(l.amount)}</b>
        <span class="note">match confidence ${Math.round(l.confidence * 100)}% · ${isAuto(l) ? "cleared automatically" : "needs an analyst"}</span></div>
    </div>
    <dl class="facts">
      <div><dt>Bank narrative</dt><dd class="mono">${esc(l.narrative)}</dd></div>
      <div><dt>Proposed as</dt><dd>${esc(l.kind)}</dd></div>
      ${l.beneficiary_account ? `<div><dt>Paid to account</dt><dd class="mono">${l.beneficiary_account}</dd></div>` : ""}
    </dl>
    ${l.event ? `<div class="event"><b>Sent to the fraud team:</b> ${esc(l.event.type)} on claim <span class="mono">${esc(l.event.claim)}</span>. This feeds the payment checks in phase 1 (RC-08).</div>` : ""}
    <section style="display:grid;gap:10px">
      <h3>Why</h3>
      <ul class="reasons" style="grid-template-columns:1fr">${l.reasons.map(r => `<li style="grid-template-columns:1fr"><span>${esc(r)}</span></li>`).join("")}</ul>
    </section>
    ${its.length ? `<section style="display:grid;gap:10px">
      <h3>Proposed match (${its.length} item${its.length > 1 ? "s" : ""})</h3>
      <div class="tablewrap"><table class="links"><thead><tr><th>Item</th><th>Kind</th><th>Reference</th><th>Party</th><th>Due</th><th style="text-align:right">Amount</th></tr></thead><tbody>
      ${its.slice(0, 40).map(i => `<tr><td class="mono">${i.id}</td><td>${i.kind}</td><td class="mono">${esc(i.ref)}</td><td>${esc(i.party)}</td><td class="num">${i.due}</td><td class="num" style="text-align:right">${money(i.amount)}</td></tr>`).join("")}
      ${its.length > 40 ? `<tr><td colspan="6" class="muted">and ${its.length - 40} more</td></tr>` : ""}
      ${its.length > 1 ? `<tr><td colspan="5"><b>Total of items</b></td><td class="num" style="text-align:right"><b>${money(total)}</b></td></tr>` : ""}
      </tbody></table></div></section>` : `<p class="note">No open item proposed. ${l.amount > 0 ? "Holds in suspense until identified (RC-10)." : ""}</p>`}
    ${l.journal ? `<div class="journal">Proposed journal, posted only after approval: <b>${money(l.journal.amount)}</b> to ${esc(l.journal.account)}.</div>` : ""}
    ${isAuto(l) || !its.length ? "" : `<section class="decide" aria-label="Decision">
      <h3>Analyst decision</h3>
      <div class="btns" role="group" aria-label="Decision">
        <button class="btn b-notfraud" data-dec="accept" aria-pressed="${d?.decision === "accept"}">Accept match</button>
        <button class="btn b-confirmed" data-dec="reject" aria-pressed="${d?.decision === "reject"}">Reject match</button>
      </div>
      <label for="note" class="note">Note. Rejections and notes teach the matcher which suggestions to trust (RC-06).</label>
      <textarea id="note" rows="2" placeholder="For a rejection, say what it should match instead">${esc(d?.note || "")}</textarea>
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <button class="btn primary" id="save">Save decision</button>
        <span class="note" id="save-msg">${d ? `Saved ${new Date(d.at).toLocaleString()}${d.by === myId ? " by you" : ""}` : (db ? "Not decided yet." : "Decisions can't be saved in this view; they last until you reload.")}</span>
      </div></section>`}
    <p class="note">Test data only: ${l.correct ? "the proposal matches the planted answer." : `the proposal does <b>not</b> match the planted answer (${esc(l.truth_kind)}).`}</p>`;
  let pick = d?.decision || null;
  el.querySelectorAll("[data-dec]").forEach(b => b.onclick = () => { pick = b.dataset.dec; el.querySelectorAll("[data-dec]").forEach(x => x.setAttribute("aria-pressed", x === b)); });
  const s = $("save"); if (s) s.onclick = () => save(l.line_id, pick, $("note").value.trim());
}

async function save(id, decision, note) {
  const msg = $("save-msg");
  if (!decision) { msg.textContent = "Pick accept or reject first."; return; }
  if (decision === "reject" && !note) { msg.textContent = "Say why you rejected it."; return; }
  if (saving) return;
  const rec = { decision, note, at: new Date().toISOString(), by: myId || null, kind: BY_ID.get(id).kind, confidence: BY_ID.get(id).confidence };
  if (!db) { decisions[id] = rec; refresh(); return; }
  saving = true; $("save").disabled = true; msg.textContent = "Saving…";
  try { await db.collection("decisions").doc(id).set(rec); decisions[id] = rec; refresh(); }
  catch (e) { msg.textContent = e?.code === "permission_denied" || e?.code === "not_granted" ? "You can view this workbench but not record decisions. Ask the owner for edit access." : "Couldn't save. Check your connection and try again."; }
  finally { saving = false; const b = $("save"); if (b) b.disabled = false; }
}

function refresh() { summary(); renderList(); renderCase(); }
function open(id) { selected = id; renderList(); renderCase(); if (window.matchMedia("(max-width: 860px)").matches) $("case").scrollIntoView({ block: "start" }); }

function backtest() {
  threshold = Number($("thr").value) / 100;
  $("thr-out").textContent = threshold.toFixed(2);
  const auto = LINES.filter(isAuto), wrong = auto.filter(l => !l.correct).length;
  $("bt-auto").textContent = (auto.length / LINES.length * 100).toFixed(1) + "%";
  $("bt-wrong").textContent = `${wrong} (${(wrong / Math.max(1, auto.length) * 100).toFixed(2)}%)`;
  $("thr-note").textContent = `${LINES.length - auto.length} lines left for analysts. Fraud events always go to a person, whatever the threshold.`;
  const kinds = {};
  LINES.forEach(l => { const k = kinds[l.truth_kind] ||= { n: 0, a: 0 }; k.n++; k.a += isAuto(l) ? 1 : 0; });
  $("bt-kinds").innerHTML = Object.entries(kinds).sort((a, b) => b[1].n - a[1].n).map(([k, v]) =>
    `<div class="hbar"><span>${esc(k)}</span><span class="track"><i style="width:${v.a / v.n * 100}%"></i></span><span class="num muted">${v.a} of ${v.n}</span></div>`).join("");
  summary(); renderList(); renderCase();
}

function ageing() {
  const order = ["Not yet due", "0 to 7 days", "8 to 30 days"];
  $("ageing").innerHTML = order.filter(k => DATA.metrics.ageing[k]).map(k => `<tr><td>${k}</td><td class="r num">${DATA.metrics.ageing[k].count}</td><td class="r num">${money(DATA.metrics.ageing[k].value)}</td></tr>`).join("");
}

document.querySelectorAll(".chip[data-f]").forEach(b => b.onclick = () => { filter = b.dataset.f; document.querySelectorAll(".chip[data-f]").forEach(x => x.setAttribute("aria-pressed", x === b)); renderList(); });
$("q").oninput = e => { query = e.target.value; renderList(); };
$("list").onclick = e => { const r = e.target.closest(".row"); if (r) open(r.dataset.id); };
document.querySelectorAll("[role=tab]").forEach(t => t.onclick = () => {
  document.querySelectorAll("[role=tab]").forEach(x => x.setAttribute("aria-selected", x === t));
  $("view-q").hidden = t.id !== "tab-q"; $("view-bt").hidden = t.id !== "tab-bt";
});
$("thr").oninput = backtest;

selected = (LINES.find(l => l.event) || LINES[0]).line_id;
ageing(); backtest();

(async () => {
  try { const user = await window.claude?.use?.("user"); if (user) myId = await user.id().catch(() => null); } catch (e) {}
  try { db = await window.claude?.use?.("db"); } catch (e) { db = null; }
  if (!db) { renderCase(); return; }
  db.collection("decisions").onSnapshot(snap => {
    const next = {};
    snap.docs.forEach(d => { const v = d.data(); if (v && DECISIONS[v.decision]) next[d.id] = v; });
    decisions = next; refresh();
  }, () => {});
})();
})();
