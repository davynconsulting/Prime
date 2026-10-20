(function () {
const DATA = window.__PRIME_DATA;
const CLAIMS = DATA.claims;
const BY_ID = new Map(CLAIMS.map(c => [c.claim_id, c]));
const LABEL_TARGET = 300;
const BASE_KEYS = new Set(["early_loss", "late_report", "no_police_report"]);
const OUTCOMES = { confirmed: "Confirmed fraud", notfraud: "Not fraud", inconclusive: "Inconclusive" };

let outcomes = {};          // claim_id -> {outcome, note, by, at}
let db = null, user = null, myId = null, saving = false;
let filter = "open", query = "", selected = null, showTruth = false;
try { showTruth = localStorage.getItem("siu-truth") === "1"; } catch (e) {}

const $ = id => document.getElementById(id);
const fmtMoney = n => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const band = s => s >= 70 ? "high" : s >= 50 ? "mid" : "low";
const esc = s => String(s ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const stateOf = id => outcomes[id]?.outcome || "open";

function summary() {
  const m = DATA.metrics;
  $("sum-claims").textContent = m.claims.toLocaleString();
  $("sum-ref").textContent = m.capacity;
  $("sum-caught").textContent = `${m.engine.fraud_caught} of ${m.planted_fraud}`;
  $("sum-caught-label").textContent = `planted fraud caught, against ${m.baseline_checklist.fraud_caught} for a checklist`;
  const historic = m.historic_confirmed;
  const fresh = Object.values(outcomes).filter(o => o.outcome === "confirmed").length;
  const total = historic + fresh;
  $("sum-labels").textContent = `${total} of ${LABEL_TARGET}`;
  $("sum-labels-label").textContent = `confirmed cases toward a trained model (${historic} historic, ${fresh} from this desk)`;
  $("sum-meter").style.width = Math.min(100, total / LABEL_TARGET * 100) + "%";
}

function visible() {
  const q = query.trim().toLowerCase();
  return CLAIMS.filter(c => {
    if (filter === "open" && (!c.referred || stateOf(c.claim_id) !== "open")) return false;
    if (filter === "done" && stateOf(c.claim_id) === "open") return false;
    if (filter === "all" && !c.referred) return false;
    if (filter === "below" && (c.referred || c.score < 20)) return false;
    if (!q) return true;
    return [c.claim_id, c.claimant, c.bank_account, c.phone, c.repairer, c.policy_id].some(v => String(v).toLowerCase().includes(q));
  });
}

function renderList() {
  const rows = visible();
  const list = $("list");
  if (!rows.length) {
    list.innerHTML = `<p class="note" style="padding:16px">${filter === "open" ? "Every referred claim has a decision. Switch to Decided to review them." : "No claims match."}</p>`;
    return;
  }
  list.innerHTML = rows.slice(0, 300).map(c => {
    const st = stateOf(c.claim_id);
    return `<button class="row" role="listitem" data-id="${c.claim_id}" aria-current="${c.claim_id === selected}">
      <div class="score s-${band(c.score)} num">${c.score}</div>
      <div class="who"><div><span class="mono">${c.claim_id}</span> · ${esc(c.claimant)}</div>
        <div class="muted" style="font-size:12.5px">${c.line} · ${c.peril} · ${fmtMoney(c.amount_claimed)}</div></div>
      <span class="state st-${st}">${st === "open" ? "To review" : OUTCOMES[st]}</span>
    </button>`;
  }).join("");
}

function renderCase() {
  const el = $("case");
  const c = BY_ID.get(selected);
  if (!c) { el.innerHTML = `<p class="muted">Pick a claim from the queue to open its case file.</p>`; return; }
  const linked = c.network_id ? CLAIMS.filter(x => x.network_id === c.network_id && x.claim_id !== c.claim_id) : [];
  const o = outcomes[c.claim_id];
  const maxPts = 30;
  el.innerHTML = `
    <div class="casehead">
      <div style="display:grid;gap:4px;min-width:0">
        <h2><span class="mono" style="font-size:16px">${c.claim_id}</span> · ${esc(c.claimant)}</h2>
        <span class="muted">${c.line} · ${c.peril} · ${c.region} region · policy <span class="mono">${c.policy_id}</span></span>
      </div>
      <div class="bigscore"><b class="num" style="color:var(--${band(c.score)})">${c.score}</b>
        <span class="note">risk score · ${c.referred ? "referred" : "below referral threshold of " + DATA.metrics.threshold}</span></div>
    </div>
    <dl class="facts">
      <div><dt>Amount claimed</dt><dd class="num">${fmtMoney(c.amount_claimed)}</dd></div>
      <div><dt>Policy started</dt><dd class="num">${c.policy_inception}</dd></div>
      <div><dt>Loss date</dt><dd class="num">${c.loss_date}</dd></div>
      <div><dt>Reported</dt><dd class="num">${c.reported_date}</dd></div>
      <div><dt>Payee account</dt><dd class="mono">${c.bank_account}</dd></div>
      <div><dt>Phone</dt><dd class="mono">${c.phone}</dd></div>
      <div><dt>Repairer</dt><dd class="mono">${c.repairer}</dd></div>
      <div><dt>Invoice</dt><dd class="mono">${c.invoice_no}</dd></div>
    </dl>
    <section style="display:grid;gap:10px">
      <h3>Why it scored ${c.score}</h3>
      ${c.reasons.length ? `<ul class="reasons">${c.reasons.map(r => `
        <li><span class="fam">${r.family}</span><span>${esc(r.reason)}</span>
          <span class="bar" title="${r.points} points"><i style="width:${Math.min(100, r.points / maxPts * 100)}%"></i></span></li>`).join("")}</ul>`
        : `<p class="note">No rule, anomaly or network signal fired.</p>`}
    </section>
    ${linked.length ? `<section style="display:grid;gap:10px">
      <h3>Linked claims (${linked.length}) sharing an account or phone</h3>
      <div class="tablewrap"><table class="links"><thead><tr><th>Claim</th><th>Claimant</th><th>Account</th><th>Phone</th><th>Repairer</th><th>Score</th><th>Decision</th></tr></thead><tbody>
      ${linked.map(l => `<tr><td><button class="chip mono" data-open="${l.claim_id}">${l.claim_id}</button></td><td>${esc(l.claimant)}</td>
        <td class="mono" style="${l.bank_account === c.bank_account ? "color:var(--high);font-weight:500" : ""}">${l.bank_account}</td>
        <td class="mono" style="${l.phone === c.phone ? "color:var(--high);font-weight:500" : ""}">${l.phone}</td>
        <td class="mono">${l.repairer}</td><td class="num">${l.score}</td><td>${l.siu_history === "confirmed" ? '<span class="state st-confirmed">Confirmed before</span>' : (outcomes[l.claim_id] ? OUTCOMES[outcomes[l.claim_id].outcome] : "–")}</td></tr>`).join("")}
      </tbody></table></div></section>` : ""}
    <section class="decide" aria-label="Record outcome">
      <h3>Investigator outcome</h3>
      <div class="btns" role="group" aria-label="Outcome">
        ${Object.entries(OUTCOMES).map(([k, v]) => `<button class="btn b-${k}" data-out="${k}" aria-pressed="${o?.outcome === k}">${v}</button>`).join("")}
      </div>
      <label for="reason" class="note">Reason (required). It becomes the label a future model learns from.</label>
      <textarea id="reason" rows="2" placeholder="What you checked and what you found">${esc(o?.note || "")}</textarea>
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <button class="btn primary" id="save">Save outcome</button>
        <span class="note" id="save-msg">${o ? `Saved ${new Date(o.at).toLocaleString()}${o.by ? ` by <span data-uid="${esc(o.by)}">${o.by === myId ? "you" : "a colleague"}</span>` : ""}` : (db ? "Not decided yet." : "Outcomes can't be saved in this view; they last until you reload.")}</span>
      </div>
      <p class="note">The system never declines a claim. A confirmed outcome goes to the claims handler for action.</p>
    </section>
    <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center">
      <label class="toggle"><input type="checkbox" id="truth" ${showTruth ? "checked" : ""}> Show planted answer (test data only)</label>
      ${showTruth ? `<span class="truth">${c.truth_fraud ? "Planted fraud: " + esc(c.truth_type) : "Planted as a genuine claim"}</span>` : ""}
    </div>`;
  let pick = o?.outcome || null;
  el.querySelectorAll("[data-out]").forEach(b => b.onclick = () => {
    pick = b.dataset.out;
    el.querySelectorAll("[data-out]").forEach(x => x.setAttribute("aria-pressed", x === b));
  });
  el.querySelectorAll("[data-open]").forEach(b => b.onclick = () => open(b.dataset.open));
  $("truth").onchange = e => { showTruth = e.target.checked; try { localStorage.setItem("siu-truth", showTruth ? "1" : "0"); } catch (err) {} renderCase(); };
  $("save").onclick = () => save(c.claim_id, pick, $("reason").value.trim());
  resolveNames();
}

async function resolveNames() {
  if (!user) return;
  const ids = [...document.querySelectorAll("[data-uid]")].map(n => n.dataset.uid).filter(id => id !== myId);
  if (!ids.length) return;
  try {
    const ps = await user.profiles(ids);
    document.querySelectorAll("[data-uid]").forEach(n => { if (n.dataset.uid !== myId) n.textContent = ps[n.dataset.uid]?.name || "a colleague"; });
  } catch (e) {}
}

async function save(id, outcome, note) {
  const msg = $("save-msg");
  if (!outcome) { msg.textContent = "Pick an outcome first."; return; }
  if (!note) { msg.textContent = "Add a reason before saving."; return; }
  if (saving) return;
  const rec = { outcome, note, at: new Date().toISOString(), by: myId || null, score: BY_ID.get(id).score };
  if (!db) { outcomes[id] = rec; afterChange(); msg.textContent = "Recorded for this session only."; return; }
  saving = true; $("save").disabled = true; msg.textContent = "Saving…";
  try {
    await db.collection("outcomes").doc(id).set(rec);
    outcomes[id] = rec; afterChange();
  } catch (e) {
    msg.textContent = e?.code === "permission_denied" || e?.code === "not_granted"
      ? "You can view this desk but not record outcomes. Ask the owner for edit access."
      : "Couldn't save. Check your connection and try again.";
  } finally { saving = false; const b = $("save"); if (b) b.disabled = false; }
}

function afterChange() { summary(); renderList(); renderCase(); }

function open(id) {
  selected = id;
  renderList(); renderCase();
  if (window.matchMedia("(max-width: 860px)").matches) $("case").scrollIntoView({ block: "start" });
}

// Back-test, recomputed live as the SIU capacity changes (FR-11)
function backtest() {
  const share = Number($("cap").value) / 100;
  $("cap-out").textContent = $("cap").value + "%";
  const n = Math.round(CLAIMS.length * share);
  const fraudTotal = CLAIMS.filter(c => c.truth_fraud).length;
  const top = CLAIMS.slice(0, n);   // already sorted by score
  const caught = top.filter(c => c.truth_fraud).length;
  const basePts = c => c.reasons.filter(r => BASE_KEYS.has(r.key)).reduce((s, r) => s + r.points, 0);
  const base = CLAIMS.filter(c => basePts(c) > 0).sort((a, b) => basePts(b) - basePts(a)).slice(0, n);
  const baseCaught = base.filter(c => c.truth_fraud).length;
  const threshold = top.length ? top[top.length - 1].score : 100;
  $("cap-note").textContent = `${n} referrals, about ${Math.round(n / 104)} a week over two years of claims. Referral threshold: score ${threshold} or above.`;
  $("bt-engine").textContent = `${caught} / ${fraudTotal}`;
  $("bt-base").textContent = `${baseCaught} / ${fraudTotal}`;
  $("bt-prec").textContent = `${Math.round(caught / Math.max(1, n) * 100)}% of the engine's referrals are planted fraud, against ${Math.round(baseCaught / Math.max(1, base.length) * 100)}% for the checklist.`;
  const types = {};
  CLAIMS.filter(c => c.truth_fraud).forEach(c => { const t = types[c.truth_type] ||= { total: 0, caught: 0 }; t.total++; });
  top.filter(c => c.truth_fraud).forEach(c => types[c.truth_type].caught++);
  $("bt-types").innerHTML = Object.entries(types).sort((a, b) => b[1].caught / b[1].total - a[1].caught / a[1].total).map(([k, v]) =>
    `<div class="hbar"><span>${esc(k)}</span><span class="track"><i style="width:${v.caught / v.total * 100}%"></i></span><span class="num muted">${v.caught} of ${v.total}</span></div>`).join("");
  const regions = {};
  CLAIMS.forEach(c => { const r = regions[c.region] ||= { claims: 0, ref: 0 }; r.claims++; });
  top.forEach(c => regions[c.region].ref++);
  const maxRate = Math.max(...Object.values(regions).map(r => r.ref / r.claims), 0.0001);
  $("bt-regions").innerHTML = Object.entries(regions).sort().map(([k, v]) =>
    `<div class="hbar"><span>${k}</span><span class="track"><i class="ref" style="width:${v.ref / v.claims / maxRate * 100}%"></i></span><span class="num muted">${(v.ref / v.claims * 100).toFixed(1)}%</span></div>`).join("");
}

// Wiring
document.querySelectorAll(".chip[data-f]").forEach(b => b.onclick = () => {
  filter = b.dataset.f;
  document.querySelectorAll(".chip[data-f]").forEach(x => x.setAttribute("aria-pressed", x === b));
  renderList();
});
$("q").oninput = e => { query = e.target.value; renderList(); };
$("list").onclick = e => { const r = e.target.closest(".row"); if (r) open(r.dataset.id); };
document.querySelectorAll("[role=tab]").forEach(t => t.onclick = () => {
  document.querySelectorAll("[role=tab]").forEach(x => x.setAttribute("aria-selected", x === t));
  $("view-desk").hidden = t.id !== "tab-desk";
  $("view-bt").hidden = t.id !== "tab-bt";
});
$("cap").oninput = backtest;

selected = CLAIMS.find(c => c.referred && c.network_id)?.claim_id || CLAIMS[0].claim_id;
summary(); renderList(); renderCase(); backtest();

// Shared outcomes: every investigator's decisions, live (SR-F09, SR-F10)
(async () => {
  try {
    user = await window.claude?.use?.("user");
    if (user) myId = await user.id().catch(() => null);
  } catch (e) {}
  try { db = await window.claude?.use?.("db"); } catch (e) { db = null; }
  if (!db) { renderCase(); return; }
  db.collection("outcomes").onSnapshot(snap => {
    const next = {};
    snap.docs.forEach(d => { const v = d.data(); if (v && OUTCOMES[v.outcome]) next[d.id] = v; });
    outcomes = next;
    afterChange();
  }, () => {});
})();
})();
