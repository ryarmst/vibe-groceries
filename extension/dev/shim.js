// Dev only: a stand-in for the WebExtension `browser` API so the pages run in a normal tab.
(() => {
  const store = (prefix) => ({
    async get(keys) {
      const list = keys == null ? Object.keys(localStorage).filter((k) => k.startsWith(prefix)).map((k) => k.slice(prefix.length))
        : Array.isArray(keys) ? keys : [keys];
      const out = {};
      for (const k of list) { const v = localStorage.getItem(prefix + k); if (v !== null) out[k] = JSON.parse(v); }
      return out;
    },
    async set(obj) { for (const [k, v] of Object.entries(obj)) localStorage.setItem(prefix + k, JSON.stringify(v)); },
    async remove(keys) { for (const k of [].concat(keys)) localStorage.removeItem(prefix + k); },
  });
  window.browser = {
    storage: { local: store("local:"), session: store("session:") },
    permissions: { request: async () => true, contains: async () => true },
    runtime: { getURL: (p) => `${location.origin}/${p}`, sendMessage: async () => null },
    tabs: { create: ({ url }) => window.open(url) },
    sidebarAction: { open: () => window.open("/ui/sidebar.html", "sidebar", "width=420,height=800") },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {} },
  };
})();
