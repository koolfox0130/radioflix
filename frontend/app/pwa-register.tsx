"use client";

import { useEffect } from "react";

export default function PwaRegister() {
  useEffect(() => {
    async function registerServiceWorker() {
      if (!("serviceWorker" in navigator)) {
        return;
      }

      try {
        await navigator.serviceWorker.register("/sw.js", {
          scope: "/",
        });

        console.log("RadioFlix service worker registered");
      } catch (error) {
        console.error("RadioFlix service worker registration failed", error);
      }
    }

    registerServiceWorker();
  }, []);

  return null;
}
