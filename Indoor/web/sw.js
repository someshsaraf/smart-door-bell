// Ring alerts while the doorbell page is closed. The Pi sends a Web Push message
// (push.py); this worker shows it as a notification: STOP stops the bell (with the
// ring's own token, no login needed), a tap opens the page at the front door.
// Later messages for the same ring (its picture, "answered") replace it quietly.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: "Doorbell", body: e.data ? e.data.text() : "" }; }
  const opts = { body: d.body || "", tag: d.tag || "doorbell", icon: "/icon-192.png", badge: "/badge-96.png", data: d,
    timestamp: (d.time || Date.now() / 1000) * 1000 };
  if (d.type === "ring") {
    opts.requireInteraction = true;
    opts.actions = [{ action: "stop", title: "■ Stop the bell" }, { action: "open", title: "See who it is" }];
    if (d.image) opts.image = d.image;
  }
  if (d.update) { opts.silent = true; opts.renotify = false; }  // the same ring again: no second sound
  else { opts.renotify = true; if (d.type === "ring") opts.vibrate = [300, 150, 300, 150, 600]; }
  e.waitUntil(self.registration.showNotification(d.title || "Doorbell", opts));
});

self.addEventListener("notificationclick", (e) => {
  const d = e.notification.data || {};
  e.notification.close();
  if (e.action === "stop") {
    e.waitUntil(fetch("/api/push/stop", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: d.token }) })
      .then((r) => self.registration.showNotification("Doorbell", { tag: "doorbell", silent: true, icon: "/icon-192.png",
        body: r.ok ? "Bell stopped" : "This ring is already over" }))
      .catch(() => self.registration.showNotification("Doorbell", { tag: "doorbell", body: "Could not reach the doorbell" })));
    return;
  }
  const page = d.type === "ring" ? "door" : "home";
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (new URL(c.url).origin === self.location.origin) { await c.focus(); c.postMessage({ go: page }); return; }
    }
    await self.clients.openWindow("/#" + page);
  })());
});

// the browser renewed this device's push address: tell the Pi (the page's login cookie goes along)
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil((async () => {
    const sub = e.newSubscription || await self.registration.pushManager.subscribe(e.oldSubscription.options);
    await fetch("/api/push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subscription: sub.toJSON(), name: "Renewed device" }) });
  })());
});
