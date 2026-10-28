self.addEventListener("push", (event) => {
  let body = "reminder";
  try {
    const data = event.data ? event.data.json() : {};
    body = data.body || data.text || body;
  } catch (err) {
    body = event.data ? event.data.text() : body;
  }
  event.waitUntil(self.registration.showNotification("admeasy", { body }));
});

self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "show" && self.registration && self.registration.showNotification) {
    event.waitUntil(self.registration.showNotification(data.title || "admeasy", {
      body: data.body || "",
    }));
  }
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow("/"));
});
