/* ============================================================
 * Pointage du personnel : visage (webcam + face-api.js) et empreinte
 * (WebAuthn / Windows Hello) — commun à la borne (rh/borne_pointage.html)
 * et à l'enregistrement des visages/empreintes (rh/gestion_rh.html).
 *
 * Patron (2026-10-10) : « le cadre dans lequel on regarde n'est pas large
 * et ça ne marche pas bien ». Avant : vidéo 320×240, une seule image par
 * enregistrement, aucune consigne. Maintenant : caméra HD, grand cadre avec
 * guide ovale et contour du visage en direct, consignes (« rapprochez-vous »,
 * « au centre »...), et plusieurs images moyennées pour enregistrer comme
 * pour reconnaître — beaucoup plus fiable.
 * ============================================================ */
const PointageBiometrie = (() => {
    const MODELES = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights';
    let modelesCharges = false;

    const CONSIGNES = {
        aucun: 'Placez votre visage dans le cadre',
        loin: 'Rapprochez-vous de la caméra',
        pres: 'Reculez un peu',
        decentre: 'Placez votre visage au centre du cadre',
        flou: 'Restez immobile, bien face à la caméra',
        ok: 'Ne bougez plus…',
    };

    function options() {
        return new faceapi.TinyFaceDetectorOptions({inputSize: 416, scoreThreshold: 0.45});
    }

    async function chargerModeles() {
        if (modelesCharges) return true;
        if (typeof faceapi === 'undefined') return false;
        try {
            await Promise.all([
                faceapi.nets.tinyFaceDetector.loadFromUri(MODELES),
                faceapi.nets.faceLandmark68Net.loadFromUri(MODELES),
                faceapi.nets.faceRecognitionNet.loadFromUri(MODELES),
            ]);
            modelesCharges = true;
            return true;
        } catch (err) {
            console.error('Modèles de reconnaissance faciale :', err);
            return false;
        }
    }

    async function ouvrirCamera(video) {
        const flux = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: {facingMode: 'user', width: {ideal: 1280}, height: {ideal: 720}},
        });
        video.srcObject = flux;
        await new Promise(r => (video.readyState >= 2 ? r() : video.addEventListener('loadeddata', r, {once: true})));
        try { await video.play(); } catch (e) { /* autoplay déjà actif */ }
        return flux;
    }

    function fermerCamera(flux) {
        if (flux) flux.getTracks().forEach(t => t.stop());
    }

    /** Une image analysée : état (aucun / loin / pres / decentre / flou / ok) et descripteur. */
    async function analyser(video) {
        if (!video.videoWidth) return {etat: 'aucun'};
        const d = await faceapi.detectSingleFace(video, options()).withFaceLandmarks().withFaceDescriptor();
        if (!d) return {etat: 'aucun'};
        const box = d.detection.box, W = video.videoWidth, H = video.videoHeight;
        const taille = box.width / W;
        const cx = (box.x + box.width / 2) / W, cy = (box.y + box.height / 2) / H;
        let etat = 'ok';
        if (taille < 0.14) etat = 'loin';
        else if (taille > 0.7) etat = 'pres';
        else if (Math.abs(cx - 0.5) > 0.24 || Math.abs(cy - 0.5) > 0.28) etat = 'decentre';
        else if (d.detection.score < 0.6) etat = 'flou';
        return {etat, box, W, H, descripteur: d.descriptor};
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
    async function echantillonner(video, n, suivi) {
        const bons = [];
        for (let essai = 0; essai < n * 5 && bons.length < n; essai++) {
            const r = await analyser(video);
            if (suivi) suivi(r, bons.length);
            if (r.etat === 'ok') bons.push(Array.from(r.descripteur));
            await new Promise(res => setTimeout(res, 180));
        }
        if (bons.length < n) return {erreur: 'Visage pas assez net : placez-vous bien face à la caméra, dans la lumière, et réessayez.'};
        if (bons.some(d => distance(d, bons[0]) > 0.45)) return {erreur: "Plusieurs visages ou mouvement pendant la prise : une seule personne, immobile, et réessayez."};
        const moyenne = bons[0].map((_, i) => bons.reduce((s, d) => s + d[i], 0) / bons.length);
        return {descripteur: moyenne};
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

    return {CONSIGNES, chargerModeles, ouvrirCamera, fermerCamera, analyser, dessiner, echantillonner, messageErreurEmpreinte};
})();
