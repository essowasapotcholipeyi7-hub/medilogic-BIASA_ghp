// ⭐ 2026-10-23 (patron) : chambre P160 vendue hors du module d'hospitalisation (vente d'actes, proformas)
// = MÊME CALCUL qu'à l'hospitalisation. Assuré AMU : la chambre est découpée par période (1re semaine,
// 8e au 14e jour, 15 jours et plus), PBR de la grille AMU du niveau de la structure (cabine 1-2 lits,
// niveau CHU : 5 000 / 3 375 / 1 625) ramené au prix clinique s'il est plus bas — calculé par le serveur
// (/api/actes_vente/chambre_paliers -> services/hospitalisation_service.lignes_chambre_vente), qui refait
// le même découpage à l'enregistrement. Non assuré : une seule ligne, comme avant.
// Les lignes d'une chambre gardent le nom du catalogue (tarifs, listes, PBR privés) ; `nom_periode` est le
// nom affiché (et celui de la ligne sur la vente). Lignes venues d'une hospitalisation (datées, ou déjà
// « 8e jour au 14e jour » / « 15 jours et plus ») : jamais touchées.
(function (global) {
    var SUITE = /(8e jour au 14e jour|8e-14e jour|8e au 14e jour|15 jours et plus)\s*$/i;

    function estChambreP160(item) {
        return !!(item && item.nom && String(item.nom).indexOf('P160') !== -1
                  && !item.date_prestation && !SUITE.test(String(item.nom)));
    }
    function cleChambreP160(item) {
        return [item.id || '', item.nom, item.service_id || '', item.medecin_id || ''].join('|');
    }
    // Toutes les lignes de la même chambre que `item`
    function lignesChambreP160(lignes, item) {
        var cle = cleChambreP160(item);
        return (lignes || []).filter(function (x) { return estChambreP160(x) && cleChambreP160(x) === cle; });
    }

    // Redécoupe les chambres de `lireLignes()` si leur durée, l'assurance ou le prix ont changé. `amu` :
    // patient assuré AMU (assurance principale active). Renvoie le nouveau tableau de lignes, ou null si
    // rien n'a changé. Le tableau est relu après les appels au serveur (il a pu changer entre-temps) : une
    // chambre dont le nombre de jours a bougé pendant l'appel est laissée telle quelle (prochain passage).
    async function decouperChambresP160(lireLignes, amu) {
        var groupes = new Map();
        (lireLignes() || []).forEach(function (item) {
            if (!estChambreP160(item)) return;
            if (item.pbr_catalogue === undefined || item.pbr_catalogue === null) item.pbr_catalogue = item.pbr;
            var cle = cleChambreP160(item);
            if (!groupes.has(cle)) groupes.set(cle, []);
            groupes.get(cle).push(item);
        });
        var remplacements = new Map();
        for (var [cle, items] of groupes) {
            var premier = items[0];
            var total = items.reduce(function (s, it) { return s + (parseInt(it.quantite) || 0); }, 0);
            var amuChambre = !!amu && premier.prise_en_charge_amu !== false;
            var signature = (amuChambre ? 'amu' : 'non') + ':' + total + ':' + premier.prix;
            if (items.every(function (it) { return it.chambre_signature === signature; })) continue;
            var lignes = null;
            if (amuChambre && total > 0) {
                var r = await fetch('/api/actes_vente/chambre_paliers', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({id: premier.id, nom: premier.nom, prix: premier.prix,
                                          pbr_catalogue: premier.pbr_catalogue, jours: total}),
                }).then(function (r) { return r.json(); }).catch(function () { return null; });
                lignes = (r && r.success && r.lignes && r.lignes.length) ? r.lignes : null;
            }
            if (!lignes) lignes = [{nom_periode: null, pbr: premier.pbr_catalogue, quantite: total}];
            var plusieurs = lignes.length > 1;
            remplacements.set(cle, {total: total, lignes: lignes.map(function (l) {
                return Object.assign({}, premier, {
                    quantite: l.quantite, pbr: l.pbr,
                    nom_periode: plusieurs ? l.nom_periode : null,
                    chambre_signature: signature,
                    total: (parseFloat(premier.prix) || 0) * l.quantite,
                    pbr_total: (parseFloat(l.pbr) || 0) * l.quantite,
                });
            })});
        }
        if (!remplacements.size) return null;
        var actuelles = lireLignes() || [];
        var fait = new Set();
        var nouveau = [];
        var change = false;
        actuelles.forEach(function (item) {
            if (!estChambreP160(item)) { nouveau.push(item); return; }
            var cle = cleChambreP160(item);
            var rempl = remplacements.get(cle);
            var totalActuel = lignesChambreP160(actuelles, item).reduce(function (s, it) { return s + (parseInt(it.quantite) || 0); }, 0);
            if (!rempl || rempl.total !== totalActuel) { nouveau.push(item); return; }
            if (fait.has(cle)) return;
            fait.add(cle);
            rempl.lignes.forEach(function (l) { nouveau.push(l); });
            change = true;
        });
        return change ? nouveau : null;
    }

    // Planifie un redécoupage (sans bloquer l'affichage) ; `appliquer(nouvellesLignes)` remplace les
    // lignes et réaffiche. Un seul passage à la fois par panier (`nomPanier`).
    var enCours = {};
    function planifierDecoupageChambres(nomPanier, lireLignes, amu, appliquer) {
        if (enCours[nomPanier] || !(lireLignes() || []).some(estChambreP160)) return;
        enCours[nomPanier] = true;
        setTimeout(async function () {
            try {
                var nouveau = await decouperChambresP160(lireLignes, amu);
                if (nouveau) appliquer(nouveau);
            } finally {
                enCours[nomPanier] = false;
            }
        }, 0);
    }

    global.estChambreP160 = estChambreP160;
    global.cleChambreP160 = cleChambreP160;
    global.lignesChambreP160 = lignesChambreP160;
    global.decouperChambresP160 = decouperChambresP160;
    global.planifierDecoupageChambres = planifierDecoupageChambres;
})(window);
