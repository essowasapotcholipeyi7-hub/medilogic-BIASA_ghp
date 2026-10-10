// ⭐ Thème — filet de sécurité générique (patron, 2026-10-09/10).
// Beaucoup de pages ont leurs propres styles (blocs à fond blanc, textes bleu
// marine, jaunes ou rouges très vifs) que la feuille du thème ne connaît pas.
// Ce script repasse sur les éléments affichés :
//   - MODE SOMBRE (html[data-bs-theme=dark]) : fond quasi blanc -> fond des
//     cartes du thème ; texte sombre sur fond sombre -> texte du thème ;
//     couleur de texte trop vive -> adoucie ;
//   - MODE CLAIR : couleur de texte trop vive (jaune, bleu, rouge saturés)
//     -> teinte plus douce et plus foncée, lisible sur fond clair ; fond jaune
//     vif posé en dur -> jaune pâle.
// Rejoué sur le contenu ajouté dynamiquement (AJAX, modals). Exposé :
// themeSombreDemarrer() / themeClairDemarrer() / themeSombreAnnuler() pour
// l'interrupteur Soleil / Lune (bascule en direct, sans recharger).
(function () {
    const root = document.documentElement;
    let CARTE = '#1E1E1E', TEXTE = '#E8E8E8', observateur = null, mode = null;
    const SKIP = new Set(['IMG', 'SVG', 'PATH', 'G', 'CANVAS', 'VIDEO', 'INPUT', 'SELECT', 'TEXTAREA', 'OPTION', 'SCRIPT', 'STYLE', 'I', 'BR', 'HR']);
    const SKIP_SEL = '.badge, .modal-backdrop, .form-check-input, .structure-brand, .alert, .progress, .spinner-border, .toast, .swal2-container, [data-th-garder]';
    const SKIP_CLAIR = '.badge, .btn, .modal-backdrop, .form-check-input, .structure-brand, .alert, .progress, .spinner-border, .toast, .swal2-container, [data-th-garder], .navbar, .top-nav, .sidebar, .hub-hero';

    function lireCouleurs() {
        const cs = getComputedStyle(root);
        CARTE = (cs.getPropertyValue('--th-carte') || '').trim() || '#1E1E1E';
        TEXTE = (cs.getPropertyValue('--th-texte') || '').trim() || '#E8E8E8';
    }
    function rgb(s) {
        const m = s && s.match(/rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?/);
        return m ? {r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4]} : null;
    }
    const lum = c => (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) / 255;
    function hsl(c) {
        const r = c.r / 255, g = c.g / 255, b = c.b / 255, max = Math.max(r, g, b), min = Math.min(r, g, b);
        const l = (max + min) / 2; let h = 0, s = 0;
        if (max !== min) {
            const d = max - min; s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
            h = max === r ? ((g - b) / d + (g < b ? 6 : 0)) : max === g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60;
        }
        return {h, s, l};
    }
    const hslTxt = (h, s, l) => `hsl(${Math.round(h)}, ${Math.round(s * 100)}%, ${Math.round(l * 100)}%)`;

    function fondEffectif(el) {
        let p = el;
        while (p && p !== document.documentElement) {
            const b = rgb(getComputedStyle(p).backgroundColor);
            if (b && b.a > 0.5) return lum(b);
            p = p.parentElement;
        }
        const b = rgb(getComputedStyle(document.body).backgroundColor);
        return b ? lum(b) : (mode === 'sombre' ? 0 : 1);
    }
    function poser(el, prop, valeur) {
        el.style.setProperty(prop, valeur, 'important');
        el.dataset.thSombre = '1';
    }

    function corrigerSombre(el) {
        if (SKIP.has(el.tagName) || el.closest(SKIP_SEL)) return;
        const st = getComputedStyle(el);
        const bg = rgb(st.backgroundColor);
        if (bg && bg.a > 0.5 && lum(bg) > 0.86 && !(st.backgroundImage || '').includes('gradient')) {
            poser(el, 'background-color', CARTE);
            poser(el, 'transition', 'none');   // sinon la transition de la page masque le changement
            if (st.borderColor && lum(rgb(st.borderColor) || {r: 0, g: 0, b: 0}) > 0.8) poser(el, 'border-color', 'rgba(255,255,255,.14)');
        }
        const col = rgb(st.color);
        if (!col) return;
        if (lum(col) < 0.28 && fondEffectif(el) < 0.4) {
            poser(el, 'color', TEXTE);
        } else {
            const h = hsl(col);   // couleur trop vive (jaune, rouge, vert saturés) : adoucie
            if (h.s > 0.72 && h.l > 0.38 && h.l < 0.75) poser(el, 'color', hslTxt(h.h, Math.min(h.s, 0.55), Math.max(h.l, 0.66)));
        }
    }

    function corrigerClair(el) {
        if (SKIP.has(el.tagName) || el.closest(SKIP_CLAIR)) return;
        const st = getComputedStyle(el);
        const bg = rgb(st.backgroundColor);
        if (bg && bg.a > 0.5 && !(st.backgroundImage || '').includes('gradient')) {
            const hb = hsl(bg);   // fond jaune / orange vif posé en dur -> pâle, texte foncé
            if (hb.s > 0.8 && hb.l > 0.42 && hb.l < 0.7 && hb.h >= 30 && hb.h <= 65) {
                poser(el, 'background-color', hslTxt(hb.h, 0.7, 0.9));
                poser(el, 'color', '#5C4300');
                return;
            }
        }
        const col = rgb(st.color);
        if (!col) return;
        const h = hsl(col);
        if (h.s > 0.72 && h.l > 0.35 && h.l < 0.72 && fondEffectif(el) > 0.6) {
            poser(el, 'color', hslTxt(h.h, Math.min(h.s, 0.6), Math.min(h.l, 0.4)));
        }
    }

    function corriger(racine) {
        const fn = mode === 'sombre' ? corrigerSombre : corrigerClair;
        const els = racine.querySelectorAll ? racine.querySelectorAll('*') : [];
        let n = 0;
        if (racine !== document && racine.nodeType === 1) fn(racine);
        for (const el of els) {
            if (++n > 8000) break;
            fn(el);
        }
    }

    let minuteur = null;
    const enAttente = new Set();
    function planifier(noeud) {
        enAttente.add(noeud);
        clearTimeout(minuteur);
        minuteur = setTimeout(() => {
            const lot = Array.from(enAttente); enAttente.clear();
            lot.forEach(n => { if (n.isConnected) corriger(n); });
        }, 200);
    }

    function annuler() {
        if (observateur) { observateur.disconnect(); observateur = null; }
        clearTimeout(minuteur); enAttente.clear();
        document.querySelectorAll('[data-th-sombre]').forEach(el => {
            ['background-color', 'color', 'transition', 'border-color'].forEach(p => el.style.removeProperty(p));
            delete el.dataset.thSombre;
        });
        mode = null;
    }
    function demarrerMode(m) {
        if (mode === m) return;
        if (mode) annuler();
        mode = m;
        lireCouleurs();
        corriger(document.body);
        observateur = new MutationObserver(muts => {
            muts.forEach(x => {
                x.addedNodes.forEach(n => { if (n.nodeType === 1) planifier(n); });
                // nos propres écritures de style ne doivent pas nous relancer (boucle) ; un changement de classe, si
                if (x.type === 'attributes' && x.target.nodeType === 1 && !(x.attributeName === 'style' && x.target.dataset.thSombre)) planifier(x.target);
            });
        });
        observateur.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class']});
    }
    function demarrerSombre() { if (root.getAttribute('data-bs-theme') === 'dark') demarrerMode('sombre'); }
    function demarrerClair() { if (root.getAttribute('data-bs-theme') !== 'dark') demarrerMode('clair'); }
    function demarrerAuto() { if (root.getAttribute('data-bs-theme') === 'dark') demarrerSombre(); else demarrerClair(); }

    window.themeSombreDemarrer = demarrerSombre;
    window.themeClairDemarrer = demarrerClair;
    window.themeSombreAnnuler = annuler;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrerAuto); else demarrerAuto();
    window.addEventListener('load', () => { if (mode) corriger(document.body); });
})();
