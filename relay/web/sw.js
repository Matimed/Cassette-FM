// Service worker mínimo de cassette-fm: Chrome lo pide para instalar la página como app. No guarda nada en caché ni intercepta
// pedidos a propósito: la radio es en vivo y el audio (/api/escuchar) no puede pasar por acá.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
