/* Shows a notification for reminder messages from the helper page.
   Web Push from Lightsail needs a VAPID key the backend does not expose yet. */
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
