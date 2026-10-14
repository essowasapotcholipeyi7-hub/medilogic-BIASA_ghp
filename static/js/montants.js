/* ⭐ Montants — patron, 2026-10-14 :
 * « je veux des chiffres ronds avec espacement : 3 450 567 565 FCFA »
 * « les cartes qui montrent les sommes (CA, caisse disponible) : qu'on clique
 *   dessus avant de voir, histoire de cacher un peu les chiffres ».
 *
 * formatEntier(n)  → "3 450 567 565"       (arrondi au franc, espaces insécables)
 * formatFCFA(n)    → "3 450 567 565 FCFA"
 *
 * Montant masqué : mettre la classe « montant-masquable » sur l'élément qui
 * porte la somme (le script de la page continue d'y écrire normalement). Il
 * s'affiche « ••••••• FCFA » ; un clic sur la carte qui le contient
 * (attribut data-montants-caches) ou sur le montant lui-même le révèle, sans
 * déclencher l'action de la carte. data-montants-caches="bascule" : un
 * nouveau clic le recache. Les montants d'un même groupe
 * (data-groupe-montants="x") se révèlent ensemble.
 */
(function () {
    'use strict';

    function formatEntier(n) {
        var v = Math.round(Number(n) || 0);
        var signe = v < 0 ? '-' : '';
        // Espace insécable classique (U+00A0) : présente dans toutes les polices,
        // contrairement à l'espace fine (U+202F) que produit toLocaleString('fr-FR').
        return signe + String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    }

    function formatFCFA(n) {
        return formatEntier(n) + ' FCFA';
    }

    window.formatEntier = formatEntier;
    window.formatFCFA = formatFCFA;

    var css = ''
        + '.montant-masquable{position:relative;}'
        + '.montant-masquable:not(.revele){visibility:hidden;cursor:pointer;}'
        + '.montant-masquable:not(.revele)::after{content:"\\2022\\2022\\2022\\2022\\2022\\2022\\2022\\00a0 FCFA";'
        + 'visibility:visible;position:absolute;inset:0;text-align:inherit;white-space:nowrap;letter-spacing:.08em;}'
        + '[data-montants-caches] .montant-indice{font-size:.72rem;opacity:.7;}'
        + '[data-montants-caches].montants-reveles .montant-indice{display:none;}'
        + '.montant-masquable.revele{animation:montantApparait .35s ease;}'
        + '@keyframes montantApparait{from{opacity:0;filter:blur(6px);}to{opacity:1;filter:none;}}';
    var style = document.createElement('style');
    style.id = 'styleMontantsMasques';
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);

    function montantsDe(element) {
        var groupe = element.getAttribute('data-groupe-montants');
        if (groupe) {
            return document.querySelectorAll('[data-groupe-montants="' + groupe + '"] .montant-masquable, .montant-masquable[data-groupe-montants="' + groupe + '"]');
        }
        return element.classList.contains('montant-masquable') ? [element] : element.querySelectorAll('.montant-masquable');
    }

    function basculer(conteneur, reveler) {
        var cibles = montantsDe(conteneur);
        for (var i = 0; i < cibles.length; i++) cibles[i].classList.toggle('revele', reveler);
        var groupe = conteneur.getAttribute('data-groupe-montants');
        var cartes = groupe ? document.querySelectorAll('[data-montants-caches][data-groupe-montants="' + groupe + '"]') : [conteneur];
        for (var j = 0; j < cartes.length; j++) cartes[j].classList.toggle('montants-reveles', reveler);
    }

    // Phase de capture : le premier clic révèle et n'ouvre pas ce que la carte ouvre d'habitude.
    document.addEventListener('click', function (e) {
        var cible = e.target;
        if (!cible || !cible.closest) return;
        var conteneur = cible.closest('[data-montants-caches]') || cible.closest('.montant-masquable');
        if (!conteneur) return;
        var montants = montantsDe(conteneur);
        if (!montants.length) return;
        var masques = false;
        for (var i = 0; i < montants.length; i++) if (!montants[i].classList.contains('revele')) masques = true;
        if (masques) {
            e.preventDefault();
            e.stopPropagation();
            basculer(conteneur, true);
        } else if (conteneur.getAttribute('data-montants-caches') === 'bascule') {
            e.preventDefault();
            e.stopPropagation();
            basculer(conteneur, false);
        }
    }, true);
})();
