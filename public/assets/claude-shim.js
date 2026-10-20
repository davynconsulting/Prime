// Stands in for the claude.ai page runtime, so the three desks run on any static host.
//   db     -> shared storage through /api/records when it is configured (Vercel + Redis),
//             otherwise this browser's localStorage
//   sample -> /api/extract, which calls Claude on the server; absent when no API key is set
//   user   -> an anonymous id kept in this browser
(function () {
  const api = path => new URL("api/" + path, document.baseURI).toString();

  async function probe(path) {
    try {
      const r = await fetch(api(path), { headers: { accept: "application/json" } });
      if (!r.ok || !(r.headers.get("content-type") || "").includes("json")) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  let statusPromise = null;
  function status() {
    statusPromise ||= Promise.all([probe("records?status=1"), probe("extract")]).then(([rec, ex]) => ({
      sharedStore: !!(rec && rec.enabled),
      claude: !!(ex && ex.enabled),
    }));
    return statusPromise;
  }

  const lsKey = c => "prime-ai:" + c;
  function readLocal(c) {
    try { return JSON.parse(localStorage.getItem(lsKey(c)) || "{}"); } catch (e) { return {}; }
  }
  function writeLocal(c, map) {
    try { localStorage.setItem(lsKey(c), JSON.stringify(map)); } catch (e) {}
  }

  function makeDb(shared) {
    const cache = {}, listeners = {};
    const snapshot = map => ({
      docs: Object.entries(map).map(([id, v]) => ({ id, exists: true, data: () => v })),
    });
    const emit = c => (listeners[c] || []).forEach(fn => fn(snapshot(cache[c] || {})));

    async function load(c) {
      if (!shared) { cache[c] = readLocal(c); return; }
      const r = await fetch(api("records?collection=" + encodeURIComponent(c)));
      if (!r.ok) throw { code: "unavailable", message: "Shared storage did not answer." };
      cache[c] = (await r.json()).docs || {};
    }

    return {
      collection(c) {
        return {
          doc(id) {
            return {
              async set(data) {
                if (shared) {
                  const r = await fetch(api("records"), {
                    method: "POST",
                    headers: { "content-type": "application/json" },
                    body: JSON.stringify({ collection: c, id, data }),
                  });
                  if (!r.ok) throw { code: r.status === 403 ? "permission_denied" : "unavailable" };
                }
                cache[c] = { ...(cache[c] || (shared ? {} : readLocal(c))), [id]: data };
                if (!shared) writeLocal(c, cache[c]);
                emit(c);
              },
            };
          },
          onSnapshot(next, error) {
            (listeners[c] ||= []).push(next);
            const tick = () => load(c).then(() => emit(c)).catch(e => error && error(e));
            tick();
            const timer = shared ? setInterval(tick, 15000) : null;
            const onStorage = e => { if (e.key === lsKey(c)) tick(); };
            if (!shared) addEventListener("storage", onStorage);
            return () => {
              clearInterval(timer);
              removeEventListener("storage", onStorage);
              listeners[c] = (listeners[c] || []).filter(fn => fn !== next);
            };
          },
        };
      },
    };
  }

  const user = {
    async id() {
      try {
        let id = localStorage.getItem("prime-ai:uid");
        if (!id) { id = "u_" + Math.random().toString(36).slice(2, 12); localStorage.setItem("prime-ai:uid", id); }
        return id;
      } catch (e) {
        return null;
      }
    },
    async profiles() { return {}; },
  };

  const sample = {
    // The intake desk sends {email, received}; the server holds the prompt, so the
    // API key can't be used for anything else through this endpoint.
    async json(input) {
      const r = await fetch(api("extract"), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(input),
      });
      if (r.status === 429) throw { code: "rate_limited" };
      if (r.status === 503) throw { code: "not_granted" };
      if (!r.ok) throw { code: "error" };
      return (await r.json()).result;
    },
  };

  window.claude = {
    async use(name) {
      const s = await status();
      if (name === "db") return makeDb(s.sharedStore);
      if (name === "user") return user;
      if (name === "sample") return s.claude ? sample : null;
      return null;
    },
    status,
  };
})();
