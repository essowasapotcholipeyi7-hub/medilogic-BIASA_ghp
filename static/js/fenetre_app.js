/* ⭐ Patron (2026-10-07) : « des boutons s'ouvrent dans le navigateur
   ailleurs et, même si on les ferme, on reste dans le navigateur » — tout
   ce qui s'ouvrait dans un nouvel onglet (reçus, PDF, impressions, liens
   WhatsApp, sites AMU...) s'ouvre désormais dans une fenêtre de
   l'application, exactement comme le bouton « Imprimer le planning » :
   on la ferme et on retrouve l'application là où on l'avait laissée.
   Chargé une seule fois par base.html (et par les reçus autonomes) :
   - window.open(url, '_blank') sans options  -> fenêtre de l'application ;
   - clic sur un lien target="_blank"          -> idem (Ctrl/Shift/clic
     milieu gardent le comportement normal du navigateur). */
(function () {
    if (window.__fenetreAppInstallee) return;
    window.__fenetreAppInstallee = true;

    var ouvrirOriginal = window.open;

    function optionsFenetre(grande) {
        var largeur = Math.min(grande ? 1200 : 900, (window.screen.availWidth || 1200) - 40);
        var hauteur = Math.min(grande ? 800 : 700, (window.screen.availHeight || 800) - 60);
        var gauche = Math.max(0, Math.round(((window.screen.availWidth || largeur) - largeur) / 2));
        var haut = Math.max(0, Math.round(((window.screen.availHeight || hauteur) - hauteur) / 2));
        return 'popup=yes,width=' + largeur + ',height=' + hauteur + ',left=' + gauche + ',top=' + haut +
            ',resizable=yes,scrollbars=yes,toolbar=no,menubar=no,location=no,status=no';
    }

    function estLienExterne(url) {
        return /^(mailto|tel|sms):/i.test(String(url || ''));
    }

    window.ouvrirFenetreApp = function (url, grande) {
        if (estLienExterne(url)) { window.location.href = url; return null; }
        var f = ouvrirOriginal.call(window, url, '_blank', optionsFenetre(grande !== false));
        if (f && f.focus) { try { f.focus(); } catch (e) { /* fenêtre bloquée */ } }
        return f;
    };

    window.open = function (url, cible, options) {
        var nouvelOnglet = cible === undefined || cible === null || cible === '' || cible === '_blank';
        if (nouvelOnglet && !options) return window.ouvrirFenetreApp(url);
        return ouvrirOriginal.call(window, url, cible, options);
    };

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        var cible = e.target;
        var lien = cible && cible.closest ? cible.closest('a[target="_blank"]') : null;
        if (!lien || lien.hasAttribute('download')) return;
        var href = lien.getAttribute('href');
        if (!href || href === '#' || /^javascript:/i.test(href)) return;
        e.preventDefault();
        if (!window.ouvrirFenetreApp(lien.href) && !estLienExterne(lien.href)) {
            // fenêtre bloquée par le navigateur : on garde l'ancien comportement
            ouvrirOriginal.call(window, lien.href, '_blank');
        }
    }, true);
})();
