// Service worker: only here so browsers treat OBS Remote as an installable app.
// It caches nothing. Every request goes straight to the PC, so updates show up on the next reload,
// and an app that can't reach the PC says so instead of showing an old copy.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
