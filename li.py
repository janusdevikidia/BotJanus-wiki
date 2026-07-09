import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import pywikibot
from pywikibot import pagegenerators

# CONFIGURATION — modifier ici selon les besoins, puis lancer le script tel quel

DRY_RUN = False             # True = simulation, aucune écriture sur le wiki
DELAY_BETWEEN_PAGES = 5     # pause en secondes entre deux pages traitées (throttle poli)
DELAY_DAYS = 7              # nombre de jours avant expiration (doit rester cohérent avec le modèle, 604800 s = 7 jours)
PAGE_LIMIT = None           # None = pas de limite ; mettre un entier (ex: 10) pour tester sur un petit lot

CATEGORY_NAME = "Licence inconnue"          # Catégorie:Licence inconnue
TEMPLATE_NAME = "Licence inconnue / LI"      # nom(s) du modèle à repérer dans le wikitexte (alias inclus)
SI_TEMPLATE_NAME = "SI"                      # {{SI|...}}
BOT_NAME = "BotJanus"                        # nom du bot à mentionner dans le bandeau {{SI}}

EDIT_SUMMARY = (
    "Bot : pose de {{SI}} — licence inconnue depuis plus de %d jours "
    "(détection basée sur l'historique de {{Licence inconnue}})" % DELAY_DAYS
)

SI_REASON = "[Message automatique] Licence inconnue depuis plus d'une semaine."

TEMPLATE_RE = re.compile(
    r"\{\{\s*(?:[Ll]icence\s+inconnue|LI)\s*(?=[|}\s])", re.UNICODE
)
SI_RE = re.compile(r"\{\{\s*SI\b", re.UNICODE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("botjanus")

def find_template_addition_date(page):
    try:
        current_text = page.text
    except Exception as e:
        log.warning("  Impossible de lire le texte actuel de %s : %s", page.title(), e)
        return None

    if not TEMPLATE_RE.search(current_text):
        # Le modèle n'est plus dans la version actuelle : rien à faire.
        return None

    last_addition_ts = None
    previously_present = False

    try:
        revisions = list(page.revisions(reverse=True, content=True))
    except Exception as e:
        log.warning("  Impossible de récupérer l'historique de %s : %s", page.title(), e)
        return None

    for rev in revisions:
        rev_text = rev.text if rev.text is not None else ""
        present_now = bool(TEMPLATE_RE.search(rev_text))
        if present_now and not previously_present:
            # Transition absent -> présent : nouvelle pose du bandeau
            last_addition_ts = rev.timestamp
        previously_present = present_now

    if last_addition_ts is None:

        if revisions:
            first_text = revisions[0].text or ""
            if TEMPLATE_RE.search(first_text):
                last_addition_ts = revisions[0].timestamp

    if last_addition_ts is None:
        return None

    if last_addition_ts.tzinfo is None:
        last_addition_ts = last_addition_ts.replace(tzinfo=timezone.utc)

    return last_addition_ts


def already_tagged(text):
    """True si {{SI...}} est déjà présent dans le texte actuel."""
    return bool(SI_RE.search(text))


def build_new_text(text):

    match = TEMPLATE_RE.search(text)
    if not match:
        return text  # ne devrait pas arriver, on a déjà vérifié la présence
    insert_pos = match.start()
    si_banner = "{{%s|%s|%s}}\n" % (SI_TEMPLATE_NAME, SI_REASON, BOT_NAME)
    return text[:insert_pos] + si_banner + text[insert_pos:]


def process_page(page, dry_run, delay_days):
    log.info("Traitement de %s", page.title())

    try:
        text = page.text
    except Exception as e:
        log.error("  Erreur de lecture : %s", e)
        return

    if already_tagged(text):
        log.info("  -> déjà taggé {{%s}}, on ignore.", SI_TEMPLATE_NAME)
        return

    addition_date = find_template_addition_date(page)
    if addition_date is None:
        log.info("  -> {{%s}} introuvable dans l'historique ou déjà retiré, on ignore.", TEMPLATE_NAME)
        return

    now = datetime.now(timezone.utc)
    age = now - addition_date
    threshold = timedelta(days=delay_days)

    log.info(
        "  -> {{%s}} posé le %s UTC (il y a %s), seuil = %s",
        TEMPLATE_NAME, addition_date.isoformat(), age, threshold,
    )

    if age < threshold:
        log.info("  -> pas encore expiré, on ignore.")
        return

    new_text = build_new_text(text)
    if new_text == text:
        log.warning("  -> aucune modification produite (cas inattendu), on ignore.")
        return

    if dry_run:
        log.info("  -> [DRY-RUN] aurait ajouté {{%s}} sur %s", SI_TEMPLATE_NAME, page.title())
        return

    try:
        page.text = new_text
        page.save(summary=EDIT_SUMMARY, minor=False, bot=True)
        log.info("  -> {{%s}} ajouté avec succès sur %s", SI_TEMPLATE_NAME, page.title())
    except Exception as e:
        log.error("  -> échec de la sauvegarde sur %s : %s", page.title(), e)

def main():
    if DRY_RUN:
        log.info("=== MODE DRY-RUN : aucune modification ne sera écrite sur le wiki ===")

    site = pywikibot.Site()  # utilise le site configuré par défaut dans user-config.py
    site.login()

    category = pywikibot.Category(site, CATEGORY_NAME)
    generator = pagegenerators.CategorizedPageGenerator(category)

    count = 0
    for page in generator:
        if PAGE_LIMIT is not None and count >= PAGE_LIMIT:
            log.info("Limite de %d pages atteinte, arrêt.", PAGE_LIMIT)
            break
        try:
            process_page(page, dry_run=DRY_RUN, delay_days=DELAY_DAYS)
        except Exception as e:
            log.error("Erreur inattendue sur %s : %s", page.title(), e)
        count += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    log.info("Terminé. %d page(s) examinée(s).", count)


if __name__ == "__main__":
    main()