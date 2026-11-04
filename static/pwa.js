(() => {
  const installButton = document.getElementById("installer-app");
  let installPrompt = null;

  const isInstalled = () => window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
  const hideInstallButton = () => {
    if (installButton) installButton.style.display = "none";
  };
  const showInstallButton = () => {
    if (installButton) installButton.style.display = "";
  };

  if (isInstalled() && installButton) {
    hideInstallButton();
  }

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    }, { once: true });
  }

  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    installPrompt = event;
    if (installButton && !isInstalled()) showInstallButton();
  });

  if (installButton) {
    installButton.addEventListener("click", async () => {
      if (installPrompt) {
        installPrompt.prompt();
        const result = await installPrompt.userChoice;
        installPrompt = null;
        if (result.outcome === "accepted") hideInstallButton();
        return;
      }

      if (isInstalled()) {
        hideInstallButton();
        return;
      }

      if (!window.isSecureContext) {
        window.alert("Pour installer l’application sur un téléphone, ouvre-la depuis une adresse HTTPS accessible sur Internet.");
      } else if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
        window.alert("Dans Safari, touche Partager, puis « Sur l’écran d’accueil ». ");
      } else {
        window.alert("Dans le menu du navigateur (⋮), choisis « Installer l’application » ou « Ajouter à l’écran d’accueil ». ");
      }
    });
  }

  window.addEventListener("appinstalled", () => {
    hideInstallButton();
  });
})();
