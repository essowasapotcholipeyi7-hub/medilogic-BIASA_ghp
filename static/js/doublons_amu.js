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

    // ⭐ 2026-10-24 (patron) : patient AMU hospitalisé — injections IM / IV et perfusions incluses dans le
    // forfait P160 : l'AMU ne les prend pas (la complémentaire puis le patient les paient). Même règle que
    // services/tarification_service.py:inclus_hospitalisation() ; acte sans code reconnu par son nom.
    var INCLUS_HOSPIT = { P152: true, P153: true, P154: true };
    var NOM_INCLUS_HOSPIT = /^\s*(injections?\s+(i\.?\s*m\.?|i\.?\s*v\.?d?|intra[\s-]*(musculaire|veineuse))\b|perfusions?\b)/i;

    function inclusHospitalisation(item) {
        var type = String(item.type || '').toLowerCase();
        if (type.indexOf('produit') >= 0 || type.indexOf('pharma') >= 0 || type.indexOf('medicament') >= 0) return false;
        var premier = String(item.nom || '').trim().split(/\s+/)[0].toUpperCase();
        if (/^[A-Z][0-9]{3}$/.test(premier)) return !!INCLUS_HOSPIT[premier];
        return NOM_INCLUS_HOSPIT.test(String(item.nom || ''));
    }

    // Marque item.amu_doublon = true sur les lignes suivantes d'un code déjà vu sous un
    // AUTRE nom (le même acte sur deux lignes reste couvert, comme une quantité 2).
    // Ne touche jamais à item.prise_en_charge_amu (le choix fait sur la ligne).
    // ⭐ Et (amu_inclus_hospit) les injections / perfusions si le panier contient un P160 (même décoché pour
    // l'AMU) ou si le patient est hospitalisé (`hospitalise`, sinon window.PATIENT_HOSPITALISE_AMU).
    function marquerDoublonsAMU(liste, hospitalise) {
        var vus = {};
        (liste || []).forEach(function (item) {
            if (!item) return;
            item.amu_doublon = false;
            item.amu_inclus_hospit = false;
            if (item.prise_en_charge_amu === false) return;
            var code = codeActeAMU(item.nom);
            if (!code || EXCLUS[code]) return;
            var nom = String(item.nom || '').trim();
            if (!(code in vus)) { vus[code] = nom; return; }
            if (vus[code] !== nom) item.amu_doublon = true;
        });
        if (hospitalise === undefined) hospitalise = !!window.PATIENT_HOSPITALISE_AMU;
        var avecP160 = hospitalise || (liste || []).some(function (item) {
            return item && String(item.nom || '').trim().split(/\s+/)[0].toUpperCase() === 'P160';
        });
        if (avecP160) {
            (liste || []).forEach(function (item) {
                if (!item || item.prise_en_charge_amu === false || item.amu_doublon || !inclusHospitalisation(item)) return;
                item.amu_doublon = true;          // tous les calculs du panier : l'AMU ne prend pas la ligne
                item.amu_inclus_hospit = true;    // affichage : « inclus dans l'hospitalisation »
            });
        }
        return liste;
    }

    window.codeActeAMU = codeActeAMU;
    window.marquerDoublonsAMU = marquerDoublonsAMU;
    window.inclusHospitalisationAMU = inclusHospitalisation;
})();
