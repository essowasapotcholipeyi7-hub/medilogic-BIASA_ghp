// ⭐ Listes de prix choisies à la vente (patron, 2026-10-19, Clinique Valeo) — partagé par la vente
// d'actes, les proformas et l'hospitalisation ; miroir de services/hospitalisation_service.listes_tarifs()
// et de services/tarification_service.entree_privee() / arrondir_part_patient().
//
// Par défaut la grande liste (tarif selon l'assurance du patient). Une liste choisie (« Liste
// Expatriés », « Liste SMA »…) remplace ce tarif pour toute la vente. Liste « remise » en plusieurs
// pourcentages (SMA 20 % / 25 %) : le patient paie le tarif ; le taux DOIT être choisi sur chaque ligne
// dont le prix diffère d'un taux à l'autre (la biologie), le plus grand s'applique au reste.
// Liste Expatriés : l'assurance du patient paie sa part selon le taux de sa carte.
let LISTES_TARIFS = [];
let PAS_ARRONDI = 0;
let listeTarifActive = null;
const LISTES_MAPS = {};

function initListesTarifs(listes, pas) {
    LISTES_TARIFS = listes || [];
    PAS_ARRONDI = parseFloat(pas) || 0;
}
function groupeListeActif() { return LISTES_TARIFS.find(g => g.groupe === listeTarifActive) || null; }
function listeAPlusieursTaux(g) { return !!(g && g.remise && g.variantes.length > 1); }
function tarifEntreeListe(entree, item) {
    if (!entree) return 0;
    if (item && item.nuit && parseFloat(entree.tarif_nuit) > 0) return parseFloat(entree.tarif_nuit);
    return parseFloat(entree.tarif_prive) || 0;
}
// le taux change-t-il le prix de cette ligne ? (biologie SMA : oui ; radio, consultation : non)
function ligneDoitChoisirTaux(item, g) {
    if (!listeAPlusieursTaux(g)) return false;
    const prix = new Set(g.variantes.map(v => tarifEntreeListe((LISTES_MAPS[v.cle] || {})[item.nom], item)));
    return prix.size > 1;
}
function cleListeParDefaut(item, g) { return ligneDoitChoisirTaux(item, g) ? null : g.defaut; }
function chargerCartesListe(g) {
    if (!g) return Promise.resolve();
    return Promise.all(g.variantes.filter(v => !LISTES_MAPS[v.cle]).map(v =>
        fetch('/api/pbr-complementaires?compagnie=' + encodeURIComponent(v.cle))
            .then(r => r.json()).then(m => { LISTES_MAPS[v.cle] = m || {}; })
            .catch(() => { LISTES_MAPS[v.cle] = {}; })));
}
// entrée {tarif_prive, pbr_1, tarif_nuit, pbr_nuit} de la ligne dans la liste choisie
function entreeListe(item, g) {
    return g ? (LISTES_MAPS[item.liste_tarif || g.defaut] || {})[item.nom] : undefined;
}
// choisit la liste pour toute la vente ; `lignes` reçoivent leur variante par défaut
async function choisirListeTarif(groupe, lignes) {
    listeTarifActive = groupe || null;
    const g = groupeListeActif();
    await chargerCartesListe(g);
    (lignes || []).forEach(item => { item.liste_tarif = g ? cleListeParDefaut(item, g) : null; });
    return g;
}
// ⭐ ligne tarifée par une liste « remise » (SMA) : aucune part d'assurance privée ; une ligne absente
// de la liste suit l'assurance réelle du patient (miroir de tarification_service.ligne_remise)
function ligneRemiseListe(item, g) { return !!(g && g.remise && entreeListe(item, g)); }
function lignesListeSansTaux(lignes) { return groupeListeActif() ? (lignes || []).filter(i => !i.liste_tarif).length : 0; }
function texteInfoListe(g) {
    if (!g) return '';
    if (g.remise) return `<span class="text-warning"><i class="fas fa-percent"></i> Réduction : le patient paie le tarif ${g.libelle}.`
        + (listeAPlusieursTaux(g) ? ' Biologie : choisir le taux sur chaque ligne en rouge.' : '') + '</span>';
    return `<span class="text-info"><i class="fas fa-globe"></i> Tarif ${g.libelle} ; l'assurance du patient paie selon le taux de sa carte (sinon le patient paie tout).</span>`;
}
// <select> du taux sur une ligne ; `fonction` = nom de la fonction de la page appelée avec (index, cle)
function selectVarianteListe(item, index, g, fonction) {
    const options = g.variantes.map(v => `<option value="${v.cle}"${item.liste_tarif === v.cle ? ' selected' : ''}>Réduction ${v.pct} %</option>`).join('');
    return `<select class="form-select form-select-sm mt-1 ${item.liste_tarif ? '' : 'border-danger text-danger'}" style="width: 150px; margin: 0 auto;"`
        + ` onchange="${fonction}(${index}, this.value)"><option value="">— taux ${g.libelle} ? —</option>${options}</select>`;
}
// ⭐ Part patient arrondie au multiple de `pas` le plus proche (moitié vers le haut) : 3 696 -> 3 700
function arrondirPartPatient(montant, pas) {
    if (!(pas > 0) || montant <= 0) return montant;
    return Math.floor(montant / pas + 0.5 + 1e-9) * pas;
}
function arrondiActif(idInterrupteur) {
    const t = document.getElementById(idInterrupteur || 'toggleArrondiPatient');
    return PAS_ARRONDI > 0 && (!t || t.checked);
}
