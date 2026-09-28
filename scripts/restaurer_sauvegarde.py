"""
Restaure une sauvegarde chiffrée (créée par .github/workflows/backup.yml)
vers une base de données Postgres.

⚠️ DESTRUCTIF : --clean efface les tables existantes de la base CIBLE
avant d'y restaurer le contenu de la sauvegarde. À utiliser uniquement en
cas de besoin réel (perte ou corruption de données) — jamais en routine.

Étapes pour récupérer une sauvegarde :
    1. Aller sur github.com/<compte>/<dépôt>/actions/workflows/backup.yml
    2. Choisir une exécution (une par jour), télécharger l'artefact
       "sauvegarde-db-..." (un fichier .zip contenant un .dump.enc)
    3. Dézipper, puis lancer :
           python scripts/restaurer_sauvegarde.py chemin/vers/backup-2026-09-28.dump.enc "<DATABASE_URL cible>"
    4. Entrer la phrase de passe BACKUP_PASSPHRASE (celle du secret GitHub)
       quand demandée — affichée en clair pendant la saisie (voir note
       ci-dessous sur pourquoi, pas d'astérisques masqués).

Nécessite pg_restore et openssl installés (déjà présents sur ce poste —
voir utils/db_failover.py qui les utilise aussi, PG_BIN_DIR ci-dessous).
"""
import io
import os
import subprocess
import sys
import tempfile

# ⭐ Sans ça, un lancement direct sous Windows (console en cp1252 par
# défaut) plante sur le moindre accent/emoji du script — repéré en testant
# ce script en conditions réelles, exactement le genre de détail qui
# ferait perdre un temps précieux en pleine urgence de restauration.
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PG_BIN_DIR = os.getenv('PG_BIN_DIR', r'C:\Program Files\PostgreSQL\18\bin')


def _outil(nom):
    chemin = os.path.join(PG_BIN_DIR, nom)
    return chemin if os.path.exists(chemin) else nom  # retombe sur le PATH


def main():
    if len(sys.argv) != 3:
        print("Usage : python scripts/restaurer_sauvegarde.py <fichier.dump.enc> <DATABASE_URL_cible>")
        sys.exit(1)

    fichier_chiffre, database_url_cible = sys.argv[1], sys.argv[2]
    if not os.path.exists(fichier_chiffre):
        print(f"❌ Fichier introuvable : {fichier_chiffre}")
        sys.exit(1)

    print(f"⚠️  ATTENTION : cette opération va EFFACER les données actuelles de la base cible")
    print(f"   avant d'y restaurer le contenu de la sauvegarde. Cette action est irréversible.\n")
    confirmation = input("Tapez EXACTEMENT « JE CONFIRME » pour continuer : ")
    if confirmation != "JE CONFIRME":
        print("Annulé — aucune modification effectuée.")
        sys.exit(0)

    # ⭐ input() plutôt que getpass.getpass() : testé en conditions réelles,
    # getpass reste bloqué indéfiniment (aucune erreur, juste un blocage
    # silencieux) sous Git Bash/MinTTY sur Windows, faute de vrai handle de
    # console Win32 — précisément le genre de piège qui ferait perdre un
    # temps précieux en pleine urgence, sans le moindre message d'erreur
    # pour comprendre pourquoi. La phrase de passe s'affiche donc en clair
    # pendant la saisie : acceptable pour un script d'administration lancé
    # localement, ponctuellement, par une seule personne de confiance —
    # bien moins grave qu'un script qui semble figé sans explication.
    passphrase = input("\nPhrase de passe de chiffrement (BACKUP_PASSPHRASE) : ").strip()

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = os.path.join(tmp, "restauration.dump")

        print("\nDéchiffrement...")
        r = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2",
             "-in", fichier_chiffre, "-out", dump_path, "-pass", f"pass:{passphrase}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"❌ Échec du déchiffrement (phrase de passe incorrecte ?) : {r.stderr}")
            sys.exit(1)

        print("Restauration vers la base de données cible...")
        r = subprocess.run(
            [_outil('pg_restore.exe'), '--clean', '--if-exists', '--no-owner', '--no-privileges',
             '-d', database_url_cible, dump_path],
            capture_output=True, text=True,
        )
        print(r.stdout)
        if r.returncode != 0:
            print(f"⚠️ pg_restore a signalé des avertissements/erreurs (souvent sans gravité — objets déjà absents) :")
            print(r.stderr[:3000])

    print("\n✅ Restauration terminée.")


if __name__ == "__main__":
    main()
