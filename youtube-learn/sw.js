// 클립러닝 서비스 워커: 앱 화면을 저장해 두어 빠르게 열리고, 오프라인에서도 보관함을 볼 수 있게 한다.
// API 요청(/api/)은 절대 저장하지 않는다.
const CACHE = "cliplearn-v1";
const SHELL = ["./", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || url.pathname.includes("/api/")) return;

  // 화면(HTML)은 네트워크 우선: 새 버전을 바로 반영하고, 안 되면 저장본을 쓴다
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put("./", copy)); return res; })
        .catch(() => caches.match("./"))
    );
    return;
  }
  // 아이콘 등 정적 파일은 저장본 우선
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
