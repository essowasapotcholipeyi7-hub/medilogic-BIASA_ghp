# -*- coding: utf-8 -*-
"""Feuilles « tableur » stockées dans Neon — étape 2 de l'abandon de Google Sheets (patron, 2026-10-18).

Les feuilles de produits (struct_N_produits) sont lues et écrites par le code comme un tableur : par
ligne et par colonne (colonne F = stock), en insérant / supprimant des lignes, en complétant l'en-tête...
Plutôt que de réécrire chaque endroit, FeuilleNeon offre les mêmes opérations que gspread (get_all_values,
get_all_records, row_values, col_values, find, cell, update_cell, update, batch_update, append_row,
insert_row, delete_rows) sur une table de Neon : chaque ligne du tableur est une ligne de la table
(rang = numéro de ligne, valeurs = textes des cellules). Le reste du code ne change pas ; tout va en
quelques millisecondes au lieu d'aller chez Google.

ClasseurNeon enveloppe le classeur Google : les feuilles concernées (FEUILLES_NEON) sont servies par
Neon, toutes les autres restent chez Google. ajuster_stock() fait une entrée / sortie de stock en UNE
requête (deux ventes simultanées ne s'écrasent plus)."""
import re

from services.comptes_service import executer

# feuilles servies par Neon (étape 2 : produits ; étape 3 : actes)
FEUILLES_NEON = (re.compile(r'^struct_-?\d+_produits$'), re.compile(r'^struct_-?\d+_actes$'))

# ⭐ Copie en mémoire par feuille, valable tant que son numéro de version (feuilles_neon.version, augmenté à
# chaque écriture, dans la même transaction) n'a pas changé : une lecture ne coûte qu'une toute petite requête,
# et une écriture faite par l'autre processus du serveur est vue aussitôt.
import threading
_copies = {}
_verrou_copies = threading.Lock()
_MAJ_VERSION = "UPDATE feuilles_neon SET version = version + 1 WHERE feuille = %s"

COLONNE_STOCK = 6   # F


def est_feuille_neon(nom):
    return bool(nom) and any(m.match(nom) for m in FEUILLES_NEON)


# ------------------------------------------------------------------ outils
def _lettres_vers_num(lettres):
    n = 0
    for c in lettres.upper():
        n = n * 26 + (ord(c) - 64)
    return n


def _a1(ref):
    """'F12' -> (12, 6) ; 'F' -> (None, 6) ; '12' -> (12, None)."""
    m = re.fullmatch(r"(?:'?[^!]*'?!)?\$?([A-Za-z]*)\$?(\d*)", ref.strip())
    if not m:
        raise ValueError(f"Plage inconnue : {ref}")
    lettres, chiffres = m.groups()
    return (int(chiffres) if chiffres else None, _lettres_vers_num(lettres) if lettres else None)


def _texte_cellule(v):
    """Valeur écrite -> texte stocké, comme Google Sheets l'afficherait (USER_ENTERED)."""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


class Cellule:
    def __init__(self, row, col, value):
        self.row, self.col, self.value = row, col, value

    def __repr__(self):
        return f"<Cellule R{self.row}C{self.col} {self.value!r}>"


class FeuilleIntrouvable(Exception):
    pass


class FeuilleNeon:
    """Même interface (le sous-ensemble utilisé par l'appli) qu'un gspread.Worksheet."""

    def __init__(self, titre):
        self.title = titre
        self.id = titre

    # ---------------------------------------------------------- lecture
    def _lignes(self):
        v = executer("SELECT version FROM feuilles_neon WHERE feuille = %s", (self.title,))
        version = v[0]['version'] if v else None
        copie = _copies.get(self.title)
        if version is not None and copie and copie[0] == version:
            return [list(r) for r in copie[1]]
        grille = self._lire_grille()
        if version is not None:
            with _verrou_copies:
                _copies[self.title] = (version, grille)
        return [list(r) for r in grille]

    def _lire_grille(self):
        lignes = executer("SELECT rang, valeurs FROM feuilles_neon_lignes WHERE feuille = %s ORDER BY rang", (self.title,))
        grille, attendu = [], 1
        for l in lignes:
            while attendu < l['rang']:      # trous (ne devrait pas arriver) : lignes vides
                grille.append([])
                attendu += 1
            grille.append([_texte_cellule(v) for v in (l['valeurs'] or [])])
            attendu += 1
        # comme Google : pas de lignes vides à la fin
        while grille and not any(c != '' for c in grille[-1]):
            grille.pop()
        return grille

    def get_all_values(self, *args, **kwargs):
        grille = self._lignes()
        largeur = max((len(r) for r in grille), default=0)
        return [r + [''] * (largeur - len(r)) for r in grille]

    get_values = get_all_values

    def get_all_records(self, *args, **kwargs):
        from gspread.utils import numericise_all
        valeurs = self.get_all_values()
        if not valeurs:
            return []
        cles = valeurs[0]
        return [dict(zip(cles, numericise_all(r, empty2zero=False, default_blank=''))) for r in valeurs[1:]]

    def row_values(self, rang, *args, **kwargs):
        l = executer("SELECT valeurs FROM feuilles_neon_lignes WHERE feuille = %s AND rang = %s", (self.title, rang))
        r = [_texte_cellule(v) for v in (l[0]['valeurs'] if l else [])]
        while r and r[-1] == '':
            r.pop()
        return r

    def col_values(self, col, *args, **kwargs):
        r = [(l[col - 1] if len(l) >= col else '') for l in self._lignes()]
        while r and r[-1] == '':
            r.pop()
        return r

    def find(self, query, in_row=None, in_column=None, case_sensitive=True):
        cible = str(query)
        for i, ligne in enumerate(self._lignes(), start=1):
            if in_row is not None and i != in_row:
                continue
            for j, v in enumerate(ligne, start=1):
                if in_column is not None and j != in_column:
                    continue
                if (v == cible) if case_sensitive else (v.lower() == cible.lower()):
                    return Cellule(i, j, v)
        return None

    def cell(self, row, col, *args, **kwargs):
        r = self.row_values(row)
        return Cellule(row, col, r[col - 1] if len(r) >= col else '')

    @property
    def row_count(self):
        return max(len(self._lignes()), 1000)

    @property
    def col_count(self):
        return max((len(r) for r in self._lignes()), default=26)

    # ---------------------------------------------------------- écriture
    def _ecrire_cellules(self, ecritures):
        """ecritures = {(rang, col): texte} — en une transaction par ligne touchée."""
        par_ligne = {}
        for (rang, col), v in ecritures.items():
            par_ligne.setdefault(rang, {})[col] = v
        for rang, cellules in par_ligne.items():
            existante = executer("SELECT valeurs FROM feuilles_neon_lignes WHERE feuille = %s AND rang = %s", (self.title, rang))
            ligne = [_texte_cellule(v) for v in (existante[0]['valeurs'] if existante else [])]
            for col, v in cellules.items():
                while len(ligne) < col:
                    ligne.append('')
                ligne[col - 1] = v
            self._poser_ligne(rang, ligne)

    def _poser_ligne(self, rang, ligne):
        import json
        executer("""INSERT INTO feuilles_neon_lignes (feuille, rang, valeurs) VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (feuille, rang) DO UPDATE SET valeurs = EXCLUDED.valeurs;
                    """ + _MAJ_VERSION,
                 (self.title, rang, json.dumps(ligne, ensure_ascii=False), self.title), lire=False)

    def update_cell(self, row, col, value):
        self._ecrire_cellules({(row, col): _texte_cellule(value)})

    def update(self, *args, **kwargs):
        """update(range_name, values) ou update(values, range_name) — comme gspread (deux ordres)."""
        plage = kwargs.get('range_name')
        valeurs = kwargs.get('values')
        pos = list(args)
        if pos and isinstance(pos[0], str):
            plage = plage or pos.pop(0)
        if pos:
            valeurs = valeurs if valeurs is not None else pos.pop(0)
        if pos and plage is None and isinstance(pos[0], str):
            plage = pos.pop(0)
        if valeurs is None:
            raise ValueError("update() sans valeurs")
        if not isinstance(valeurs, list) or (valeurs and not isinstance(valeurs[0], list)):
            valeurs = [[valeurs]] if not isinstance(valeurs, list) else [valeurs]
        debut = (plage or 'A1').split(':')[0]
        rang0, col0 = _a1(debut)
        rang0, col0 = rang0 or 1, col0 or 1
        ecritures = {}
        for i, ligne in enumerate(valeurs):
            for j, v in enumerate(ligne):
                ecritures[(rang0 + i, col0 + j)] = _texte_cellule(v)
        self._ecrire_cellules(ecritures)
        return {'updatedRange': plage}

    def batch_update(self, donnees, **kwargs):
        for d in donnees:
            self.update(d['range'], d['values'])
        return {}

    def append_row(self, valeurs, **kwargs):
        rang = len(self._lignes()) + 1
        self._poser_ligne(rang, [_texte_cellule(v) for v in valeurs])
        return {}

    def append_rows(self, lignes, **kwargs):
        for l in lignes:
            self.append_row(l)
        return {}

    def insert_row(self, valeurs, index=1, **kwargs):
        import json
        # décalage en deux temps dans UNE transaction (numéros négatifs provisoires : pas de collision de clé)
        executer("""UPDATE feuilles_neon_lignes SET rang = -(rang + 1) WHERE feuille = %s AND rang >= %s;
                    UPDATE feuilles_neon_lignes SET rang = -rang WHERE feuille = %s AND rang < 0;
                    INSERT INTO feuilles_neon_lignes (feuille, rang, valeurs) VALUES (%s, %s, %s::jsonb);
                    """ + _MAJ_VERSION,
                 (self.title, index, self.title, self.title, index,
                  json.dumps([_texte_cellule(v) for v in valeurs], ensure_ascii=False), self.title), lire=False)
        return {}

    def delete_rows(self, debut, fin=None):
        fin = fin or debut
        executer("""DELETE FROM feuilles_neon_lignes WHERE feuille = %s AND rang BETWEEN %s AND %s;
                    UPDATE feuilles_neon_lignes SET rang = -(rang - %s) WHERE feuille = %s AND rang > %s;
                    UPDATE feuilles_neon_lignes SET rang = -rang WHERE feuille = %s AND rang < 0;
                    """ + _MAJ_VERSION,
                 (self.title, debut, fin, fin - debut + 1, self.title, fin, self.title, self.title), lire=False)
        return {}

    def delete_row(self, index):
        return self.delete_rows(index)

    def clear(self):
        executer("DELETE FROM feuilles_neon_lignes WHERE feuille = %s; " + _MAJ_VERSION, (self.title, self.title), lire=False)

    def __repr__(self):
        return f"<FeuilleNeon {self.title!r}>"


_existantes = set()   # feuilles dont l'existence est déjà vérifiée (une feuille n'est jamais supprimée)


def feuille_existe(titre):
    if titre in _existantes:
        return True
    if executer("SELECT 1 FROM feuilles_neon WHERE feuille = %s", (titre,)):
        _existantes.add(titre)
        return True
    return False


def creer_feuille(titre):
    executer("INSERT INTO feuilles_neon (feuille) VALUES (%s) ON CONFLICT DO NOTHING", (titre,), lire=False)
    _existantes.add(titre)
    return FeuilleNeon(titre)


class GoogleIndisponible(Exception):
    pass


class ClasseurNeon:
    """Enveloppe le classeur Google : les feuilles FEUILLES_NEON sont servies par Neon, le reste par Google.
    `classeur_google` peut être None (Google absent) : les feuilles Neon marchent quand même, une autre
    feuille est simplement introuvable (get_all_records la lit alors vide, comme une feuille absente)."""

    def __init__(self, classeur_google):
        self._google = classeur_google

    def worksheet(self, titre):
        if est_feuille_neon(titre):
            if not feuille_existe(titre):
                import gspread
                raise gspread.exceptions.WorksheetNotFound(titre)
            return FeuilleNeon(titre)
        if self._google is None:
            import gspread
            raise gspread.exceptions.WorksheetNotFound(titre)
        return self._google.worksheet(titre)

    def add_worksheet(self, title, rows=1000, cols=26, *args, **kwargs):
        if est_feuille_neon(title):
            return creer_feuille(title)
        if self._google is None:
            raise GoogleIndisponible(f"Google Sheets absent : feuille « {title} » non créée")
        return self._google.add_worksheet(title=title, rows=rows, cols=cols, *args, **kwargs)

    def worksheets(self):
        neon = [FeuilleNeon(l['feuille']) for l in executer("SELECT feuille FROM feuilles_neon ORDER BY feuille")]
        if self._google is None:
            return neon
        return neon + [w for w in self._google.worksheets() if not est_feuille_neon(w.title)]

    def __getattr__(self, nom):
        if nom.startswith('__') or self.__dict__.get('_google') is None:
            raise GoogleIndisponible(f"Google Sheets absent ({nom})")
        return getattr(self._google, nom)


# ------------------------------------------------------------------ stock en une requête
def ajuster_stock(titre, produit_id, delta, colonne=COLONNE_STOCK):
    """Ajoute `delta` (négatif = sortie) au stock du produit `produit_id` (colonne A) en UNE requête —
    deux ventes simultanées ne peuvent plus s'écraser. Le stock ne descend pas sous 0.
    Renvoie (ancien, nouveau, numéro de ligne) ou None si le produit est introuvable."""
    idx = colonne - 1
    lignes = executer(f"""
        WITH version AS (UPDATE feuilles_neon SET version = version + 1 WHERE feuille = %s RETURNING 1),
        cible AS (
            SELECT rang, valeurs,
                   COALESCE(NULLIF(regexp_replace(replace(COALESCE(valeurs->>{idx}, ''), ',', '.'), '[^0-9.\\-]', '', 'g'), '')::numeric, 0) AS ancien
            FROM feuilles_neon_lignes
            WHERE feuille = %s AND rang > 1 AND trim(valeurs->>0) = %s
            ORDER BY rang LIMIT 1
            FOR UPDATE
        )
        UPDATE feuilles_neon_lignes l
        SET valeurs = (
            SELECT jsonb_agg(CASE WHEN i - 1 = {idx} THEN to_jsonb(trunc(GREATEST(c.ancien + %s, 0))::text) ELSE e END ORDER BY i)
            FROM jsonb_array_elements(
                CASE WHEN jsonb_array_length(l.valeurs) > {idx} THEN l.valeurs
                     ELSE l.valeurs || (SELECT jsonb_agg('""'::jsonb) FROM generate_series(1, {idx} + 1 - jsonb_array_length(l.valeurs)))
                END) WITH ORDINALITY AS t(e, i))
        FROM cible c
        WHERE l.feuille = %s AND l.rang = c.rang
        RETURNING c.ancien, l.valeurs->>{idx} AS nouveau, l.rang
    """, (titre, titre, str(produit_id).strip(), delta, titre))
    if not lignes:
        return None
    l = lignes[0]
    return int(l['ancien']), int(float(l['nouveau'])), l['rang']
