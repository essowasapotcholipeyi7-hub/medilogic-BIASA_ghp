// ⭐ Patron (2026-10-09) : charge « Salaire du personnel » liée à la paie RH —
// on choisit l'employé (ou une paie globale du mois), la description et le
// montant (net calculé par la paie) se remplissent, et à la validation le
// bulletin est généré/payé par la RH : la dépense rejoint le compte
// « Salaires » (661) en comptabilité, comme un paiement fait depuis la RH.
// Utilisé par depenses_saisie.html et admin_finances.html (mêmes ids).
(function () {
    let apercu = null;
    const $ = (id) => document.getElementById(id);
    const F = (n) => Math.round(n || 0).toLocaleString('fr-FR') + ' FCFA';

    function moisCourant() {
        const d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    }

    window.chargeSalaireToggle = function (motif) {
        const bloc = $('salaireDiv');
        if (!bloc) return;
        const actif = motif === 'salaire';
        bloc.style.display = actif ? 'block' : 'none';
        const montant = $('depenseMontant');
        if (!actif) {
            if (montant && montant.dataset.salaireVerrou === '1') { montant.readOnly = false; delete montant.dataset.salaireVerrou; }
            return;
        }
        if (!$('salaireMois').value) $('salaireMois').value = moisCourant();
        window.chargerApercuSalaires();
    };

    window.chargerApercuSalaires = function () {
        const mois = $('salaireMois').value;
        const sel = $('salaireEmploye');
        const detail = $('salaireDetail');
        sel.innerHTML = '<option value="">Chargement…</option>';
        detail.textContent = '';
        fetch('/api/depenses/salaire/apercu?mois=' + encodeURIComponent(mois))
            .then(r => r.json())
            .then(d => {
                if (!d.success) { sel.innerHTML = '<option value="">-- Erreur : ' + (d.error || 'inconnue') + ' --</option>'; return; }
                apercu = d;
                const aucun = $('salaireAucunPersonnel');
                if (!d.employes.length) {
                    aucun.style.display = 'block';
                    sel.innerHTML = '<option value="">-- Aucun personnel enregistré --</option>';
                    return;
                }
                aucun.style.display = 'none';
                let html = '<option value="">-- Choisir l\'employé à payer --</option>';
                html += '<option value="__global__">💼 Paie globale ' + d.libelle_mois + ' — ' + d.nb_a_payer + ' employé(s) à payer, ' + F(d.total_a_payer) + '</option>';
                d.employes.forEach(e => {
                    const etat = e.deja_payee ? ' — déjà payé' : (e.a_payer ? ' — net ' + F(e.net_prevu) + (e.paie_statut ? '' : ' (estimé)') : ' — ' + e.motif_blocage);
                    html += '<option value="' + e.id + '"' + (e.a_payer ? '' : ' disabled') + '>' + e.nom + ' ' + e.prenom + (e.poste ? ' (' + e.poste + ')' : '') + etat + '</option>';
                });
                sel.innerHTML = html;
                window.appliquerChoixSalaire();
            })
            .catch(() => { sel.innerHTML = '<option value="">-- Erreur réseau --</option>'; });
    };

    window.appliquerChoixSalaire = function () {
        if (!apercu) return;
        const choix = $('salaireEmploye').value;
        const montant = $('depenseMontant');
        const desc = $('depenseDescription');
        const detail = $('salaireDetail');
        montant.readOnly = false; delete montant.dataset.salaireVerrou;
        if (!choix) { detail.textContent = ''; return; }
        if (choix === '__global__') {
            const cibles = apercu.employes.filter(e => e.a_payer);
            montant.value = Math.round(apercu.total_a_payer);
            montant.readOnly = true; montant.dataset.salaireVerrou = '1';
            desc.value = 'Paie globale ' + apercu.libelle_mois + ' — ' + cibles.length + ' employé(s) : ' + cibles.map(e => e.nom + ' ' + e.prenom).join(', ');
            detail.innerHTML = cibles.length
                ? '<ul class="mb-0">' + cibles.map(e => '<li>' + e.nom + ' ' + e.prenom + ' — net ' + F(e.net_prevu) + (e.paie_statut ? ' (bulletin ' + e.paie_statut + ')' : ' (bulletin généré à la validation)') + '</li>').join('') + '</ul>'
                : '<span class="text-danger">Aucun salaire à payer pour ce mois.</span>';
            return;
        }
        const e = apercu.employes.find(x => String(x.id) === String(choix));
        if (!e) return;
        montant.value = Math.round(e.net_prevu);
        montant.readOnly = true; montant.dataset.salaireVerrou = '1';
        desc.value = 'Salaire ' + apercu.libelle_mois + ' — ' + e.nom + ' ' + e.prenom + (e.matricule ? ' (' + e.matricule + ')' : '') + (e.poste ? ' — ' + e.poste : '');
        detail.innerHTML = 'Salaire de base ' + F(e.salaire_base) + ' → net à payer <strong>' + F(e.net_prevu) + '</strong>'
            + (e.paie_statut ? ' (bulletin RH ' + e.paie_statut + ')' : ' (estimé : le bulletin sera généré par la paie RH à la validation)')
            + ' — <a href="' + apercu.rh_url + '" target="_blank">modifier dans les Ressources humaines</a>.';
    };

    // Complète `data` avant l'envoi ; false = saisie incomplète (message affiché)
    window.chargeSalaireDonnees = async function (data) {
        const bloc = $('salaireDiv');
        if (!bloc || bloc.style.display === 'none') return true;
        const choix = $('salaireEmploye').value;
        const mois = $('salaireMois').value;
        if (!mois) { await afficherMessage('Indiquez le mois de paie.'); return false; }
        if (!choix) { await afficherMessage("Choisissez l'employé à payer, ou la paie globale du mois."); return false; }
        data.mois = mois;
        if (choix === '__global__') data.paie_globale = true; else data.employe_id = parseInt(choix, 10);
        return true;
    };
})();
