"""Build the static site in public/ from the desk templates in src/.

    python3 scripts/build.py          # pages only, using the data already in public/data
    python3 scripts/build.py --data   # regenerate the synthetic data with engine/ first

The templates are the same ones the claude.ai prototypes are built from; this script swaps the
embedded data for a fetched JSON file and loads assets/claude-shim.js in place of the claude.ai runtime.
"""
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, PUBLIC, ENGINE = ROOT / "src", ROOT / "public", ROOT / "engine"
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600'
         '&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">')

PAGES = [
    # name, template, data file, nav label
    ("fraud", "fraud.template.html", "data/scored.json", "Fraud desk"),
    ("intake", "intake.template.html", "data/fnol.json", "Claims intake"),
    ("reconciliation", "reconciliation.template.html", "data/recon.json", "Reconciliation"),
]

APP_CSS = """
/* App shell: top bar shared by every page */
html { -webkit-text-size-adjust: 100% }
body { margin: 0 }
code { font-family: var(--mono); font-size: 0.92em }
a { color: var(--accent) }
.appbar { background: var(--panel); border-bottom: 1px solid var(--line); padding-top: env(safe-area-inset-top, 0px) }
.appbar-in { max-width: 1240px; margin: 0 auto; padding-block: 10px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center }
.brand { font-family: var(--display); font-weight: 600; font-size: 16px; color: var(--ink); text-decoration: none }
.appbar nav { display: flex; flex-wrap: wrap; gap: 4px }
.appbar nav a { color: var(--muted); text-decoration: none; padding: 4px 10px; border-radius: 6px; font-weight: 500 }
.appbar nav a:hover { background: var(--soft); color: var(--ink) }
.appbar nav a[aria-current="page"] { background: var(--accent-soft); color: var(--ink) }
#app-status { margin-left: auto; font-size: 12.5px; color: var(--muted) }
.home-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px }
.home-cards .card h2 a { color: var(--ink); text-decoration: none }
.home-cards .card h2 a:hover { text-decoration: underline }
.phase { font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600 }
.lead { font-size: 16px; max-width: 68ch; margin: 0 }
"""


def run(cmd, cwd):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def build_data():
    py = sys.executable
    run([py, "generate_data.py", "2000", "7"], ENGINE)
    run([py, "score_claims.py", "0.05"], ENGINE)
    run([py, "generate_fnol.py", "40", "5"], ENGINE / "phase2_intake")
    run([py, "generate_bank.py", "11"], ENGINE / "phase3_reconciliation")
    run([py, "reconcile.py", "0.9"], ENGINE / "phase3_reconciliation")
    (PUBLIC / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(ENGINE / "scored.json", PUBLIC / "data" / "scored.json")
    shutil.copy(ENGINE / "phase2_intake" / "fnol.json", PUBLIC / "data" / "fnol.json")
    shutil.copy(ENGINE / "phase3_reconciliation" / "recon.json", PUBLIC / "data" / "recon.json")


def parts(template):
    t = template.read_text()
    title = re.search(r"<title>(.*?)</title>", t).group(1)
    style = t.split("<style>", 1)[1].split("</style>", 1)[0]
    markup = t.split("</style>", 1)[1].rsplit("<script>", 1)[0]
    script = t.rsplit("<script>", 1)[1].rsplit("</script>", 1)[0]
    return title, style, markup, script


def appbar(current):
    cur = ' aria-current="page"'
    links = "".join(f'<a href="{n}.html"{cur if n == current else ""}>{label}</a>' for n, _, _, label in PAGES)
    return (f'<header class="appbar"><div class="appbar-in"><a class="brand" href="index.html">Prime Insurance AI</a>'
            f'<nav aria-label="Desks">{links}</nav><span id="app-status" class="note"></span></div></header>')


def page(title, page_css, body, scripts):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)}</title>
{FONTS}
<link rel="stylesheet" href="assets/desk.css">
{f"<style>{page_css}</style>" if page_css.strip() else ""}
</head>
<body>
{body}
{scripts}
</body>
</html>
"""


def adapt_script(name, script):
    script = script.replace("const DATA = /*DATA*/null;", "const DATA = window.__PRIME_DATA;", 1)
    if name == "intake":
        old = 'await sample.json(prompt, { modelTier: "quick" })'
        assert old in script, "intake template changed: update the Claude call replacement"
        script = script.replace(old, 'await sample.json({ email: m.text, received: m.received }, { modelTier: "quick" })')
        script = script.replace("Reading with Claude isn't available in this view, so the rules reading is shown.",
                                "Reading with Claude is off on this deployment (no API key set), so the rules reading is shown.")
    return "(function () {\n" + script.strip() + "\n})();\n"


def build_pages():
    assets = PUBLIC / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shared_css = None
    for name, tpl, data, _ in PAGES:
        title, style, markup, script = parts(SRC / tpl)
        if "/*STYLE*/" in style:
            page_css = style.replace("/*STYLE*/", "")
        else:
            shared_css, page_css = style, ""
        (assets / f"{name}.js").write_text(adapt_script(name, script))
        scripts = (f'<script src="assets/claude-shim.js"></script>\n'
                   f'<script src="assets/boot.js" data-data="{data}" data-app="assets/{name}.js"></script>')
        (PUBLIC / f"{name}.html").write_text(page(title, page_css, appbar(name) + markup, scripts))
        print(f"  wrote public/{name}.html")
    (assets / "desk.css").write_text(shared_css.strip() + "\n" + APP_CSS)
    build_home()


def build_home():
    def metrics(f):
        try:
            return json.loads((PUBLIC / "data" / f).read_text())["metrics"] if f != "fnol.json" else None
        except FileNotFoundError:
            return None
    fm, rm = metrics("scored.json"), metrics("recon.json")
    fraud_line = (f"On the synthetic back-test it caught {fm['engine']['fraud_caught']} of {fm['planted_fraud']} planted fraud cases "
                  f"at 5% referral capacity, against {fm['baseline_checklist']['fraud_caught']} for a red-flag checklist.") if fm else ""
    recon_line = (f"On a synthetic month it cleared {rm['auto_rate']:.0%} of {rm['lines']:,} bank lines automatically, "
                  f"with {rm['wrong_auto']} wrong automatic matches.") if rm else ""
    body = f"""{appbar("")}
<main class="wrap">
  <header class="top">
    <h1>Prime Insurance AI <small>claims fraud, claims intake and bank reconciliation</small></h1>
    <span class="badge">Synthetic data, not real data</span>
  </header>
  <p class="lead">Three working desks built from the PRD and SRD. Every claim, email and bank line here is invented, so the numbers show how each engine behaves, not how it will perform on Prime's own data.</p>
  <section class="home-cards">
    <article class="card">
      <span class="phase">Phase 1</span>
      <h2><a href="fraud.html">Fraud desk</a></h2>
      <p style="margin:0">Scores every claim with rules, peer-group anomalies and network links, sends the riskiest to investigators, and saves their outcomes as training labels.</p>
      <p class="note" style="margin:0">{fraud_line}</p>
    </article>
    <article class="card">
      <span class="phase">Phase 2</span>
      <h2><a href="intake.html">Claims intake</a></h2>
      <p style="margin:0">Reads first-notice-of-loss emails, checks cover, lists missing documents, routes each claim, and settles simple ones only when the phase 1 fraud score allows.</p>
      <p class="note" style="margin:0">Reading with Claude needs an Anthropic API key on the server. Without one, the rules reading is used.</p>
    </article>
    <article class="card">
      <span class="phase">Phase 3</span>
      <h2><a href="reconciliation.html">Reconciliation</a></h2>
      <p style="margin:0">Matches bank lines to premiums and claim payments, clears confident matches, queues the rest with suggestions, and sends payment problems to the fraud team.</p>
      <p class="note" style="margin:0">{recon_line}</p>
    </article>
  </section>
</main>"""
    scripts = '<script src="assets/claude-shim.js"></script>\n<script src="assets/boot.js"></script>'
    (PUBLIC / "index.html").write_text(page("Prime Insurance AI", "", body, scripts))
    print("  wrote public/index.html")


if __name__ == "__main__":
    if "--data" in sys.argv:
        print("Generating synthetic data")
        build_data()
    print("Building pages")
    build_pages()
