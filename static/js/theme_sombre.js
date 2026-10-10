// ⭐ Thème sombre — filet de sécurité générique (patron, 2026-10-09 : « certaines
// parties restent blanches avec texte blanc devant, invisible », ex. Entente
// préalable). Beaucoup de pages ont leurs propres styles (blocs à fond blanc,
// textes bleu marine) que la feuille du thème ne connaît pas. Ce script,
// chargé seulement quand le thème est sombre (data-bs-theme="dark" posé par
// base.html), passe sur les éléments affichés :
//   - fond quasi blanc (uni, sans dégradé) -> fond des cartes du thème ;
//   - texte très sombre posé sur un fond sombre -> texte du thème.
// Rejoué sur le contenu ajouté dynamiquement (tableaux chargés en AJAX, modals).
(function () {
    const root = document.documentElement;
    if (root.getAttribute('data-bs-theme') !== 'dark') return;
    const cs = getComputedStyle(root);
    const CARTE = (cs.getPropertyValue('--th-carte') || '').trim() || '#1E1E1E';
    const TEXTE = (cs.getPropertyValue('--th-texte') || '').trim() || '#E8E8E8';
    const SKIP = new Set(['IMG', 'SVG', 'PATH', 'G', 'CANVAS', 'VIDEO', 'INPUT', 'SELECT', 'TEXTAREA', 'OPTION', 'SCRIPT', 'STYLE', 'I', 'BR', 'HR']);
    const SKIP_SEL = '.badge, .modal-backdrop, .form-check-input, .structure-brand, .alert, .progress, .spinner-border, .toast, .swal2-container, [data-th-garder]';

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

    function fondEffectif(el) {
        let p = el;
        while (p && p !== document.documentElement) {
            const b = rgb(getComputedStyle(p).backgroundColor);
            if (b && b.a > 0.5) return lum(b);
            p = p.parentElement;
        }
        const b = rgb(getComputedStyle(document.body).backgroundColor);
        return b ? lum(b) : 0;
    }

    function corrigerElement(el) {
        if (SKIP.has(el.tagName) || el.closest(SKIP_SEL)) return;
        const st = getComputedStyle(el);
        const bg = rgb(st.backgroundColor);
        if (bg && bg.a > 0.5 && lum(bg) > 0.86 && !(st.backgroundImage || '').includes('gradient')) {
            el.style.setProperty('background-color', CARTE, 'important');
            el.style.setProperty('transition', 'none', 'important');   // sinon la transition de la page masque le changement
            el.dataset.thSombre = '1';
            if (st.borderColor && lum(rgb(st.borderColor) || {r: 0, g: 0, b: 0}) > 0.8) el.style.setProperty('border-color', 'rgba(255,255,255,.14)', 'important');
        }
        const col = rgb(st.color);
        if (col && lum(col) < 0.28 && fondEffectif(el) < 0.4) {
            el.style.setProperty('color', TEXTE, 'important');
            el.dataset.thSombre = '1';
        } else if (col) {
            // ⭐ couleur de texte trop vive (jaune, rouge, vert saturés posés par la page) : adoucie
            const h = hsl(col);
            if (h.s > 0.72 && h.l > 0.38 && h.l < 0.75) {
                el.style.setProperty('color', `hsl(${Math.round(h.h)}, ${Math.round(Math.min(h.s, 0.55) * 100)}%, ${Math.round(Math.max(h.l, 0.66) * 100)}%)`, 'important');
                el.dataset.thSombre = '1';
            }
        }
    }

    function corriger(racine) {
        const els = racine.querySelectorAll ? racine.querySelectorAll('*') : [];
        let n = 0;
        if (racine !== document && racine.nodeType === 1) corrigerElement(racine);
        for (const el of els) {
            if (++n > 8000) break;
            corrigerElement(el);
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

    function demarrer() {
        corriger(document.body);
        new MutationObserver(muts => {
            muts.forEach(m => {
                m.addedNodes.forEach(n => { if (n.nodeType === 1) planifier(n); });
                // nos propres écritures de style ne doivent pas nous relancer (boucle) ; un changement de classe, si
                if (m.type === 'attributes' && m.target.nodeType === 1 && !(m.attributeName === 'style' && m.target.dataset.thSombre)) planifier(m.target);
            });
        }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class']});
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer); else demarrer();
    window.addEventListener('load', () => corriger(document.body));
})();
