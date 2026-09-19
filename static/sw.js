// static/sw.js
// ============================================================
// Service worker du portail patient — condition technique manquante pour
// que Chrome/Android propose l'installation (beforeinstallprompt) : un
// manifest seul ne suffit pas, il faut aussi un service worker enregistré
// avec un gestionnaire "fetch" (voir portail_patient.html/
// portail_resultats.html, navigator.serviceWorker.register()).
//
// ⭐ Stratégie volontairement prudente pour une page de RÉSULTATS
// MÉDICAUX : jamais de résultat périmé affiché depuis un cache. Seuls les
// fichiers statiques connus (manifest, icônes) sont mis en cache pour un
// démarrage plus rapide ; tout le reste (pages, API /api/portail-patient/
// resultats...) passe TOUJOURS par le réseau d'abord — le cache ne sert
// qu'en dernier recours si le téléphone est hors-ligne, jamais en
// remplacement silencieux d'une donnée à jour.
// ============================================================

const CACHE_NAME = 'ssoftone-portail-v1';
const ASSETS_STATIQUES = [
    '/portail-manifest.json',
    '/static/images/portail-icon-192.png',
    '/static/images/portail-icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS_STATIQUES))
            .catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cles) => Promise.all(
            cles.filter((cle) => cle !== CACHE_NAME).map((cle) => caches.delete(cle))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', (event) => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const estAssetStatique = ASSETS_STATIQUES.some((url) => request.url.endsWith(url));
    if (estAssetStatique) {
        // Rapide, change rarement : cache d'abord, réseau en secours.
        event.respondWith(
            caches.match(request).then((reponse) => reponse || fetch(request))
        );
        return;
    }

    // Résultats/pages : réseau d'abord, cache uniquement si hors-ligne.
    event.respondWith(
        fetch(request)
            .then((reponse) => {
                if (reponse && reponse.ok) {
                    const copie = reponse.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(request, copie)).catch(() => {});
                }
                return reponse;
            })
            .catch(() => caches.match(request))
    );
});
