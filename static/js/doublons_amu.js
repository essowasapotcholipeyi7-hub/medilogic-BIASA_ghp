// static/js/doublons_amu.js
// ⭐ Un seul acte par code AMU dans une même vente (patron, 2026-10-17) : la clinique
// peut éclater un code AMU en plusieurs actes (ex. Q436 « Echo Doppler des vaisseaux
// quelle que soit la région » -> écho-doppler artériel, veineux, TSA, artério-veineux),
// mais l'AMU n'en prend en charge qu'UN par vente. Les autres lignes du même code
// restent au patient ou à son assurance complémentaire (taux / PBR privé).
// Même règle que services/tarification_service.py:appliquer_code_amu_unique() — le
// serveur la réapplique de toute façon à l'enregistrement.
(function () {
    var MOTIFS = [/^P160$/, /^D000293$/, /^S1[0-2][0-9]$/, /^S130$/, /^R[1-9][0-9]{2}$/, /^Q[1-5][0-9]{2}$/];
    // codes jamais concernés : chambre (une ligne par type de chambre), lunettes
    var EXCLUS = { P160: true, D000293: true };

    function codeActeAMU(nom) {
        var premier = String(nom || '').trim().split(/\s+/)[0].toUpperCase();
        for (var i = 0; i < MOTIFS.length; i++) if (MOTIFS[i].test(premier)) return premier;
        return null;
    }

    // Marque item.amu_doublon = true sur les lignes suivantes d'un code déjà vu sous un
    // AUTRE nom (le même acte sur deux lignes reste couvert, comme une quantité 2).
    // Ne touche jamais à item.prise_en_charge_amu (le choix fait sur la ligne).
    function marquerDoublonsAMU(liste) {
        var vus = {};
        (liste || []).forEach(function (item) {
            if (!item) return;
            item.amu_doublon = false;
            if (item.prise_en_charge_amu === false) return;
            var code = codeActeAMU(item.nom);
            if (!code || EXCLUS[code]) return;
            var nom = String(item.nom || '').trim();
            if (!(code in vus)) { vus[code] = nom; return; }
            if (vus[code] !== nom) item.amu_doublon = true;
        });
        return liste;
    }

    window.codeActeAMU = codeActeAMU;
    window.marquerDoublonsAMU = marquerDoublonsAMU;
})();
