// Loads a desk's data file, then its script. Also fills the storage and Claude status in the top bar.
(function () {
  const me = document.currentScript;
  const dataUrl = me.dataset.data, appUrl = me.dataset.app;

  window.claude.status().then(s => {
    const el = document.getElementById("app-status");
    if (!el) return;
    el.textContent = (s.sharedStore ? "Shared storage on" : "Decisions saved in this browser only") +
      " · " + (s.claude ? "Claude reading on" : "Claude reading off");
  });

  if (!dataUrl) return;
  fetch(dataUrl)
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(data => {
      window.__PRIME_DATA = data;
      const s = document.createElement("script");
      s.src = appUrl;
      document.body.appendChild(s);
    })
    .catch(() => {
      const main = document.querySelector(".wrap");
      if (main) main.insertAdjacentHTML("afterbegin",
        '<p class="note" role="alert">The data file did not load. Run <code>python3 scripts/build.py</code> and check that public/data holds the JSON files.</p>');
    });
})();
