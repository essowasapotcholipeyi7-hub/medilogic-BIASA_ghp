// ⭐ Envoi rapide de fiches PDF à l'AMU (patron, 2026-10-19) — partagé par le
// billet d'hospitalisation (EP + billet), la page Entente Préalable et la
// page TPC. Les PDF sont préparés puis :
//   - « Partager » : partage natif du téléphone / de Windows (WhatsApp...),
//     tous les fichiers d'un coup ;
//   - sinon un bouton « Télécharger » PAR fichier (le navigateur bloque un
//     2e téléchargement automatique) puis « Ouvrir WhatsApp » sur le numéro
//     de dépôt, message prêt (wa.me n'accepte pas de pièce jointe).
// Autonome (pas de Bootstrap) : utilisable aussi sur le billet.
(function () {
    const CSS = `
    .envoi-amu-fond { position: fixed; inset: 0; background: rgba(15, 23, 42, .55); z-index: 20000;
                      display: flex; align-items: center; justify-content: center; padding: 16px; }
    .envoi-amu { background: #fff; color: #1a1a2e; border-radius: 12px; width: 100%; max-width: 480px;
                 box-shadow: 0 12px 40px rgba(0,0,0,.25); font: 14px/1.45 Arial, Helvetica, sans-serif; overflow: hidden; }
    .envoi-amu header { background: #0E9D67; color: #fff; padding: 12px 16px; display: flex; align-items: center; gap: 8px; }
    .envoi-amu header strong { flex: 1; font-size: 15px; }
    .envoi-amu header button { background: none; border: 0; color: #fff; font-size: 22px; line-height: 1; cursor: pointer; }
    .envoi-amu .corps { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
    .envoi-amu .etat { font-size: 13px; }
    .envoi-amu .etat.erreur { color: #b02a37; }
    .envoi-amu .fichier { display: flex; align-items: center; gap: 8px; border: 1px solid #dfe5ec; border-radius: 8px; padding: 8px 10px; }
    .envoi-amu .fichier span { flex: 1; font-size: 12px; word-break: break-all; }
    .envoi-amu .fichier small { color: #6b7280; display: block; }
    .envoi-amu .btn-e { border: 0; border-radius: 6px; padding: 9px 14px; font-size: 13px; cursor: pointer; color: #fff; background: #1a1a2e; }
    .envoi-amu .btn-e:disabled { opacity: .5; cursor: default; }
    .envoi-amu .btn-e.vert { background: #0E9D67; }
    .envoi-amu .btn-e.wa { background: #25D366; }
    .envoi-amu .btn-e.petit { padding: 6px 10px; font-size: 12px; }
    .envoi-amu .btn-e.fait { background: #6c757d; }
    .envoi-amu .aide { font-size: 12px; color: #555; }`;

    function injecterCss() {
        if (document.getElementById('envoiAmuCss')) return;
        const s = document.createElement('style');
        s.id = 'envoiAmuCss';
        s.textContent = CSS;
        document.head.appendChild(s);
    }
    function el(tag, attrs, ...enfants) {
        const e = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => { if (k === 'onclick') e.onclick = v; else e.setAttribute(k, v); });
        enfants.forEach(c => e.append(c));
        return e;
    }
    function numeroInternational(n) {
        let chiffres = (n || '').replace(/\D/g, '');
        if (chiffres.length === 8) chiffres = '228' + chiffres;   // numéro togolais sans indicatif
        return chiffres;
    }
    function taille(octets) {
        return octets > 1048576 ? (octets / 1048576).toFixed(1) + ' Mo' : Math.max(1, Math.round(octets / 1024)) + ' Ko';
    }

    // PDF servi par l'application : nom repris de l'en-tête Content-Disposition
    // (nom du patient, voir nom_fichier_pdf_amu dans app.py).
    async function depuisUrl(url, nomParDefaut) {
        const r = await fetch(url, {credentials: 'same-origin'});
        if (!r.ok || !(r.headers.get('content-type') || '').includes('pdf')) {
            throw new Error("la fiche n'a pas pu être générée (est-elle approuvée ?)");
        }
        const cd = r.headers.get('content-disposition') || '';
        const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
        return {blob: await r.blob(), nom: m ? decodeURIComponent(m[1]) : nomParDefaut};
    }

    // options : {titre, assureur ('CNSS'|'INAM'), numero, message,
    //            fichiers: [{libelle, obtenir: () => Promise<{blob, nom}>}]}
    async function ouvrir(options) {
        injecterCss();
        const etat = el('div', {class: 'etat'}, 'Préparation des fichiers PDF…');
        const zone = el('div', {style: 'display:flex; flex-direction:column; gap:8px;'});
        const fermer = () => fond.remove();
        const fond = el('div', {class: 'envoi-amu-fond'},
            el('div', {class: 'envoi-amu', role: 'dialog', 'aria-modal': 'true'},
                el('header', {}, el('strong', {}, options.titre || "Envoi à l'AMU"),
                   el('button', {type: 'button', title: 'Fermer', onclick: fermer}, '×')),
                el('div', {class: 'corps'}, etat, zone)));
        fond.addEventListener('click', e => { if (e.target === fond) fermer(); });
        document.body.appendChild(fond);

        let resultats;
        try {
            resultats = await Promise.all(options.fichiers.map(f => f.obtenir()));
        } catch (e) {
            etat.textContent = 'Préparation impossible : ' + (e.message || e);
            etat.classList.add('erreur');
            return;
        }
        const fichiers = resultats.map(r => new File([r.blob], r.nom, {type: 'application/pdf'}));
        const assureur = options.assureur || 'CNSS';
        const numero = numeroInternational(options.numero);
        etat.textContent = fichiers.length > 1 ? `✔ Les ${fichiers.length} PDF sont prêts.` : '✔ Le PDF est prêt.';

        if (navigator.canShare && navigator.canShare({files: fichiers})) {
            zone.append(el('button', {type: 'button', class: 'btn-e vert', onclick: async () => {
                try {
                    await navigator.share({files: fichiers, text: options.message || ''});
                    etat.textContent = '✔ Fichiers partagés.';
                } catch (e) {
                    if (e.name !== 'AbortError') etat.textContent = 'Partage impossible ici : téléchargez les fichiers ci-dessous.';
                }
            }}, `Partager ${fichiers.length > 1 ? 'les ' + fichiers.length + ' PDF' : 'le PDF'} (WhatsApp…)`));
            zone.append(el('div', {class: 'aide'}, 'Choisissez WhatsApp puis la conversation AMU-' + assureur
                + (options.numero ? ` (${options.numero})` : '') + '. Ou bien :'));
        }
        fichiers.forEach((f, i) => {
            const bouton = el('button', {type: 'button', class: 'btn-e petit'}, 'Télécharger');
            bouton.onclick = () => {
                const a = el('a', {href: URL.createObjectURL(f), download: f.name});
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(() => URL.revokeObjectURL(a.href), 60000);
                bouton.textContent = '✔ Téléchargé';
                bouton.classList.add('fait');
            };
            zone.append(el('div', {class: 'fichier'},
                el('span', {}, el('small', {}, options.fichiers[i].libelle || ''), f.name + ' — ' + taille(f.size)), bouton));
        });
        if (numero) {
            zone.append(el('button', {type: 'button', class: 'btn-e wa', onclick: () =>
                window.open(`https://wa.me/${numero}?text=${encodeURIComponent(options.message || '')}`, '_blank')
            }, `Ouvrir WhatsApp AMU-${assureur} (${options.numero})`));
            zone.append(el('div', {class: 'aide'}, 'Le message est prêt : joignez-y le(s) fichier(s) téléchargé(s).'));
        } else {
            zone.append(el('div', {class: 'aide'}, `Numéro WhatsApp de dépôt AMU-${assureur} non renseigné (page Entente Préalable, encadré « Dépôt par WhatsApp »).`));
        }
    }

    window.EnvoiAmu = {ouvrir, depuisUrl};
})();
