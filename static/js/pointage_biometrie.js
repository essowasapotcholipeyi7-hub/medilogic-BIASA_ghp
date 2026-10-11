/* ============================================================
 * Pointage du personnel : visage (webcam + face-api.js) et empreinte
 * (WebAuthn / Windows Hello) — commun à la borne (rh/borne_pointage.html)
 * et à l'enregistrement des visages/empreintes (rh/gestion_rh.html).
 *
 * Patron (2026-10-10) : « le cadre n'est pas large et ça ne marche pas
 * bien » puis « il faut que ce soit ultra sensible, que ça capte le visage
 * de façon rapide » et « si plus aucun visage ne passe, que la caméra se
 * ferme (batterie de la tablette) ».
 *  - suivi en direct par la SEULE détection (très rapide) ; le calcul
 *    lourd du descripteur n'est fait qu'au moment de vérifier ;
 *  - réseaux « préchauffés » dès le chargement (la 1re détection ne rame plus) ;
 *  - détecteur plus sensible (visages plus petits / moins nets acceptés) ;
 *  - minuterie de veille : caméra coupée après X minutes sans visage.
 * ============================================================ */
const PointageBiometrie = (() => {
    const MODELES = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights';
    let chargement = null;

    const CONSIGNES = {
        aucun: 'Placez votre visage dans le cadre',
        loin: 'Rapprochez-vous de la caméra',
        pres: 'Reculez un peu',
        decentre: 'Placez votre visage au centre du cadre',
        flou: 'Restez immobile, bien face à la caméra',
        ok: 'Ne bougez plus…',
    };

    // suivi en direct : petite entrée, seuil bas = détection rapide et sensible
    const optionsSuivi = () => new faceapi.TinyFaceDetectorOptions({inputSize: 320, scoreThreshold: 0.3});
    // vérification : entrée plus grande pour un cadrage précis du visage
    const optionsVerification = () => new faceapi.TinyFaceDetectorOptions({inputSize: 416, scoreThreshold: 0.35});

    async function prechauffer() {
        // la 1re inférence compile les programmes de la carte graphique (1 à 3 s) :
        // on la fait tout de suite sur une image vide plutôt que devant l'employé
        const c = document.createElement('canvas');
        c.width = c.height = 160;
        try {
            await faceapi.detectSingleFace(c, optionsSuivi());
            await faceapi.detectFaceLandmarks(c);
            await faceapi.computeFaceDescriptor(c);
        } catch (e) { /* sans gravité */ }
    }

    /** Charge (une seule fois) et préchauffe les réseaux. */
    function chargerModeles() {
        if (typeof faceapi === 'undefined') return Promise.resolve(false);
        if (!chargement) {
            chargement = Promise.all([
                faceapi.nets.tinyFaceDetector.loadFromUri(MODELES),
                faceapi.nets.faceLandmark68Net.loadFromUri(MODELES),
                faceapi.nets.faceRecognitionNet.loadFromUri(MODELES),
            ]).then(prechauffer).then(() => true).catch(err => {
                console.error('Modèles de reconnaissance faciale :', err);
                chargement = null;
                return false;
            });
        }
        return chargement;
    }

    async function ouvrirCamera(video) {
        const flux = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: {facingMode: 'user', width: {ideal: 1280}, height: {ideal: 720}, frameRate: {ideal: 30}},
        });
        video.srcObject = flux;
        await new Promise(r => (video.readyState >= 2 ? r() : video.addEventListener('loadeddata', r, {once: true})));
        try { await video.play(); } catch (e) { /* autoplay déjà actif */ }
        return flux;
    }

    function fermerCamera(flux) {
        if (flux) flux.getTracks().forEach(t => t.stop());
    }

    function evaluer(box, score, W, H) {
        const taille = box.width / W;
        const cx = (box.x + box.width / 2) / W, cy = (box.y + box.height / 2) / H;
        if (taille < 0.10) return 'loin';
        if (taille > 0.75) return 'pres';
        if (Math.abs(cx - 0.5) > 0.28 || Math.abs(cy - 0.5) > 0.32) return 'decentre';
        if (score < 0.5) return 'flou';
        return 'ok';
    }

    /** Suivi en direct (rapide) : état et cadre du visage, sans descripteur. */
    async function detecter(video) {
        if (!video.videoWidth) return {etat: 'aucun'};
        const d = await faceapi.detectSingleFace(video, optionsSuivi());
        if (!d) return {etat: 'aucun'};
        const W = video.videoWidth, H = video.videoHeight;
        return {etat: evaluer(d.box, d.score, W, H), box: d.box, W, H};
    }

    /** Analyse complète d'une image : état, cadre et descripteur (128 nombres). */
    async function analyser(video) {
        if (!video.videoWidth) return {etat: 'aucun'};
        const d = await faceapi.detectSingleFace(video, optionsVerification()).withFaceLandmarks().withFaceDescriptor();
        if (!d) return {etat: 'aucun'};
        const box = d.detection.box, W = video.videoWidth, H = video.videoHeight;
        return {etat: evaluer(box, d.detection.score, W, H), box, W, H, descripteur: d.descriptor};
    }

    /** Contour du visage sur le canevas posé par-dessus la vidéo (même miroir CSS). */
    function dessiner(canvas, resultat) {
        const ctx = canvas.getContext('2d');
        const w = canvas.clientWidth, h = canvas.clientHeight;
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        ctx.clearRect(0, 0, w, h);
        if (!resultat || !resultat.box) return;
        // la vidéo est affichée en « cover » : même mise à l'échelle que le navigateur
        const echelle = Math.max(w / resultat.W, h / resultat.H);
        const dx = (w - resultat.W * echelle) / 2, dy = (h - resultat.H * echelle) / 2;
        const b = resultat.box;
        ctx.lineWidth = 4;
        ctx.strokeStyle = resultat.etat === 'ok' ? '#3ddc84' : '#ffb020';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(dx + b.x * echelle, dy + b.y * echelle, b.width * echelle, b.height * echelle, 14);
        else ctx.rect(dx + b.x * echelle, dy + b.y * echelle, b.width * echelle, b.height * echelle);
        ctx.stroke();
    }

    function distance(a, b) {
        let s = 0;
        for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; s += d * d; }
        return Math.sqrt(s);
    }

    /** n images correctes, cohérentes entre elles, moyennées en un seul descripteur.
     *  Renvoie {descripteur} ou {erreur}. `suivi(resultat, nbOk)` est appelé à chaque image. */
    async function echantillonner(video, n, suivi, delaiMs = 60) {
        const bons = [];
        for (let essai = 0; essai < n * 4 && bons.length < n; essai++) {
            const r = await analyser(video);
            if (suivi) suivi(r, bons.length);
            if (r.etat === 'ok' || (r.descripteur && r.etat === 'flou')) bons.push(Array.from(r.descripteur));
            if (bons.length < n && delaiMs) await new Promise(res => setTimeout(res, delaiMs));
        }
        if (bons.length < n) return {erreur: 'Visage pas assez net : placez-vous bien face à la caméra, dans la lumière, et réessayez.'};
        if (bons.some(d => distance(d, bons[0]) > 0.45)) return {erreur: "Plusieurs visages ou mouvement pendant la prise : une seule personne, immobile, et réessayez."};
        const moyenne = bons[0].map((_, i) => bons.reduce((s, d) => s + d[i], 0) / bons.length);
        return {descripteur: moyenne};
    }

    /** Minuterie de veille : `quandVeille()` est appelé après `delaiMs` sans `toucher()`. */
    function minuterieVeille(delaiMs, quandVeille) {
        let id = null;
        const armer = () => { clearTimeout(id); id = setTimeout(quandVeille, delaiMs); };
        armer();
        return {toucher: armer, arreter: () => clearTimeout(id)};
    }

    /** Message clair pour une erreur WebAuthn (empreinte). */
    function messageErreurEmpreinte(err, enregistrement) {
        const nom = err && err.name;
        if (nom === 'NotAllowedError' || nom === 'AbortError')
            return "Lecture annulée ou trop longue. Recommencez : quand Windows le demande, choisissez votre nom puis posez le doigt sur le capteur.";
        if (nom === 'InvalidStateError')
            return enregistrement ? "Cette empreinte est déjà enregistrée sur ce poste pour cet employé." : "Empreinte déjà utilisée : recommencez.";
        if (nom === 'SecurityError')
            return "L'empreinte n'est utilisable que sur l'adresse sécurisée du logiciel (https) ou sur http://localhost.";
        if (nom === 'NotSupportedError')
            return "Aucun capteur d'empreinte utilisable sur ce poste (Windows Hello non configuré ?).";
        return 'Échec de la lecture : ' + ((err && err.message) || err);
    }

    return {CONSIGNES, chargerModeles, ouvrirCamera, fermerCamera, detecter, analyser, dessiner,
            echantillonner, minuterieVeille, messageErreurEmpreinte, distance};
})();
