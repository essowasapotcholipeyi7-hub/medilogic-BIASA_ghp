// static/js/mobile.js
// ============================================================
// ⭐ 2026-10-23 (patron) : GHP sur téléphone « comme WhatsApp » — voir static/css/mobile.css.
//  - bouton ☰ : ouvre / ferme le tiroir (le menu horizontal transformé), groupe de la page ouverte déplié ;
//  - sur petit écran, thème clair/sombre, langue et recherche globale passent dans le tiroir (la barre
//    du haut tient alors sur une ligne), et reviennent à leur place sur grand écran ;
//  - tout tableau de la page (même ajouté plus tard par une page) est mis dans un cadre qui défile de
//    côté, au lieu d'écraser ses colonnes lettre par lettre ou d'élargir toute la page.
// ============================================================
(function () {
    'use strict';

    const TIROIR = window.matchMedia('(max-width: 991.98px)');
    const TELEPHONE = window.matchMedia('(max-width: 767.98px)');

    // ---------- Tiroir ----------
    function groupeCourant() {
        const chemin = window.location.pathname;
        let trouve = null;
        document.querySelectorAll('.top-nav .nav-item').forEach(function (item) {
            item.querySelectorAll('a[href]').forEach(function (a) {
                if (!trouve && a.getAttribute('href') === chemin) trouve = item;
            });
        });
        return trouve;
    }

    window.basculerMenuMobile = function (ouvrir) {
        const ouvert = document.body.classList.contains('menu-mobile-ouvert');
        const doitOuvrir = (typeof ouvrir === 'boolean') ? ouvrir : !ouvert;
        document.body.classList.toggle('menu-mobile-ouvert', doitOuvrir);
        const bouton = document.getElementById('btnMenuMobile');
        if (bouton) bouton.setAttribute('aria-expanded', doitOuvrir ? 'true' : 'false');
        if (doitOuvrir) {
            const groupe = groupeCourant();
            if (groupe) {
                groupe.classList.add('courant');
                // Après coup : le clic sur ☰ remonte jusqu'au « clic ailleurs » de base.html, qui referme
                // tous les groupes ouverts.
                if (groupe.querySelector('.mega-menu')) setTimeout(function () { groupe.classList.add('open'); }, 0);
            }
        } else {
            document.querySelectorAll('.top-nav .nav-item.open').forEach(function (el) { el.classList.remove('open'); });
        }
    };

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && document.body.classList.contains('menu-mobile-ouvert')) basculerMenuMobile(false);
    });
    // Repassé en grand écran (rotation de tablette) : le tiroir n'existe plus
    TIROIR.addEventListener('change', function (e) { if (!e.matches) basculerMenuMobile(false); });

    // ---------- Outils de la barre du haut : dans le tiroir sur petit écran ----------
    const OUTILS = ['.navbar .global-search-wrapper', '#themeSoleilLune', '#langueFrEn'];
    const placesOrigine = new Map();

    function rangerOutils() {
        const cible = document.getElementById('menuMobileOutils');
        if (!cible) return;
        OUTILS.forEach(function (selecteur) {
            const el = placesOrigine.has(selecteur) ? placesOrigine.get(selecteur).el : document.querySelector(selecteur);
            if (!el) return;
            if (!placesOrigine.has(selecteur)) {
                placesOrigine.set(selecteur, {el: el, parent: el.parentNode, suivant: el.nextSibling});
            }
            const origine = placesOrigine.get(selecteur);
            if (TELEPHONE.matches) {
                if (el.parentNode !== cible) cible.appendChild(el);
            } else if (el.parentNode !== origine.parent) {
                origine.parent.insertBefore(el, origine.suivant);
            }
        });
    }
    TELEPHONE.addEventListener('change', rangerOutils);

    // ---------- Tableaux ----------
    function dejaDansUnCadre(table) {
        for (let el = table.parentElement; el && el !== document.body; el = el.parentElement) {
            if (el.classList.contains('table-responsive') || el.classList.contains('tableau-mobile')) return true;
            const ox = getComputedStyle(el).overflowX;
            if (ox === 'auto' || ox === 'scroll') return true;
            if (el.classList.contains('main-content') || el.classList.contains('modal-body')) return false;
        }
        return false;
    }

    function envelopperTableaux(racine) {
        if (!TELEPHONE.matches) return;
        (racine || document).querySelectorAll('table').forEach(function (table) {
            if (table.dataset.mobileVu) return;
            table.dataset.mobileVu = '1';
            if (table.closest('.navbar, .top-nav, .no-mobile-cadre') || dejaDansUnCadre(table)) return;
            const cadre = document.createElement('div');
            cadre.className = 'tableau-mobile';
            table.parentNode.insertBefore(cadre, table);
            cadre.appendChild(table);
        });
    }

    let attente = null;
    function surveillerTableaux() {
        envelopperTableaux(document);
        const observateur = new MutationObserver(function (mutations) {
            if (!TELEPHONE.matches) return;
            const ajoutTableau = mutations.some(function (m) {
                return Array.prototype.some.call(m.addedNodes, function (n) {
                    return n.nodeType === 1 && (n.tagName === 'TABLE' || n.querySelector && n.querySelector('table'));
                });
            });
            if (!ajoutTableau) return;
            clearTimeout(attente);
            attente = setTimeout(function () { envelopperTableaux(document); }, 80);
        });
        observateur.observe(document.body, {childList: true, subtree: true});
    }
    TELEPHONE.addEventListener('change', function (e) { if (e.matches) envelopperTableaux(document); });

    // ---------- Cartes de chiffres : deux par ligne plutôt qu'une ----------
    // (rangées de .col-md-3 / .col-md-2 / .col-lg-3 sans largeur téléphone : chaque carte « 6 Aujourd'hui »
    // prenait toute la largeur). Seulement des cartes courtes, jamais un formulaire.
    function compacterCartesChiffres() {
        if (!TELEPHONE.matches) return;
        document.querySelectorAll('.main-content .row').forEach(function (rangee) {
            if (rangee.dataset.mobileCartes) return;
            rangee.dataset.mobileCartes = '1';
            const colonnes = Array.prototype.filter.call(rangee.children, function (c) { return c.nodeType === 1; });
            if (colonnes.length < 2) return;
            const toutesCartes = colonnes.every(function (c) {
                return /\bcol-(md|lg)-[23]\b/.test(c.className) && !/\bcol-(\d+|auto)\b/.test(c.className)
                    && c.querySelector('.card') && !c.querySelector('input, select, textarea, table')
                    && (c.textContent || '').trim().length < 80;
            });
            if (toutesCartes) colonnes.forEach(function (c) { c.classList.add('col-6'); });
        });
    }

    // ---------- Barres d'action collées en bas (ex. « finaliser la vente ») ----------
    // La bulle de messagerie remonte au-dessus et le contenu garde la place de la barre (sinon la fin de
    // la page restait cachée dessous).
    function ajusterBarresBas() {
        let hauteur = 0;
        const flottants = [];   // petits boutons fixés en bas (messagerie, panier...)
        const H = window.innerHeight, L = window.innerWidth;
        Array.prototype.forEach.call(document.body.children, function (el) {
            if (el.classList.contains('modal') || el.classList.contains('top-nav')) return;
            const st = getComputedStyle(el);
            if (st.position !== 'fixed' || st.display === 'none' || st.visibility === 'hidden') return;
            if (el.dataset.basOrigine === undefined) el.dataset.basOrigine = el.style.bottom || '';
            const r = el.getBoundingClientRect();
            if (!r.height) return;
            if (r.width > L * 0.6) {
                if (r.height < H * 0.6 && Math.abs(r.bottom - H) < 4) hauteur = Math.max(hauteur, r.height);
            } else if (r.width < L * 0.4 && st.bottom !== 'auto') {
                flottants.push(el);
            }
        });
        if (!TELEPHONE.matches) hauteur = 0;
        flottants.forEach(function (el) {
            el.style.removeProperty('bottom');
            if (el.dataset.basOrigine) el.style.bottom = el.dataset.basOrigine;
            if (hauteur) {
                const bas = parseFloat(getComputedStyle(el).bottom) || 0;
                el.style.setProperty('bottom', (bas + hauteur + 6) + 'px', 'important');
            }
        });
        // La messagerie au-dessus des autres boutons du même côté (panier...) plutôt que par-dessus
        const fab = document.getElementById('chatFab');
        if (fab && hauteur && flottants.indexOf(fab) >= 0) {
            const rf = fab.getBoundingClientRect();
            let hautMin = null;
            flottants.forEach(function (el) {
                if (el === fab) return;
                const r = el.getBoundingClientRect();
                if (r.right > rf.left && r.left < rf.right && r.bottom > rf.top) hautMin = hautMin === null ? r.top : Math.min(hautMin, r.top);
            });
            if (hautMin !== null) fab.style.setProperty('bottom', (H - hautMin + 6) + 'px', 'important');
        }
        const contenu = document.getElementById('mainContent');
        if (contenu) contenu.style.setProperty('padding-bottom', hauteur ? (hauteur + 16) + 'px' : '', hauteur ? 'important' : '');
    }

    document.addEventListener('DOMContentLoaded', function () {
        rangerOutils();
        surveillerTableaux();
        compacterCartesChiffres();
        ajusterBarresBas();
        window.addEventListener('resize', ajusterBarresBas);
        setInterval(function () { if (!document.hidden) ajusterBarresBas(); }, 1500);
        // Un lien du tiroir suivi : on le referme (utile quand la page ne se recharge pas, ex. ancre)
        document.querySelectorAll('.top-nav .mega-menu a[href], .top-nav a.nav-link-top[href]').forEach(function (a) {
            a.addEventListener('click', function () {
                if (TIROIR.matches && a.getAttribute('href') && a.getAttribute('href') !== '#') basculerMenuMobile(false);
            });
        });
    });
})();
