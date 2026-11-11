# Umsetzungsplan und Erledigt-Übersicht

Stand: Auswertung der vorhandenen Projektdateien. Ein Häkchen bedeutet, dass die Grundlage dokumentiert ist – nicht, dass die Funktion bereits programmiert wurde.

## Erledigt: Grundlagen

- [x] Projektziel, Rolle als Hörer/Leser und Spoilerschutz beschrieben (`README.md`).
- [x] Verbindliche Weltregeln, Menschen und Aureas beschrieben (`WELT_REGELN.md`).
- [x] Veröffentlichungs- und Weltzeit, Handlungsebenen, Stränge und Ripple-Prinzip beschrieben (`ZEIT_UND_STRAENGE.md`).
- [x] Agentenablauf, JSON-Beispiel, Stack-Vorschläge und Qualitätsmaße dokumentiert (`PIPELINE.md`).
- [x] Datenmodell und Trennung von öffentlichem Inhalt und Backstage-Wissen skizziert (`DATENMODELL.md`).
- [x] Anforderungen an Hörbuchproduktion und Folgenübergänge skizziert (`HOERBUCH.md`).
- [x] Sieben fachliche Entscheidungen als offen erfasst (`OFFENE_PUNKTE.md`).

## Erledigt: Verwaltung und KI-Weltenbau (2026-11-07)

- [x] Lokale Oberfläche (`python3 -m story_world`): Übersicht, Projektstatus, Welt-Daten, Lücken, Impulse, KI-Vorschläge, Protokoll, Einstellungen.
- [x] Mehrere Welten als getrennte SQLite-Dateien in `welten/`.
- [x] Versionierte Migrationen (`PRAGMA user_version`) mit automatischer Sicherung vor Schemaänderungen; manuelle Sicherung per Knopf.
- [x] Herkunft (Nutzer/KI) und Sichtbarkeit (offen/backstage) je Datensatz; Geheimfelder serverseitig gefiltert.
- [x] Startbestand ausschließlich aus WELT_REGELN.md/OFFENE_PUNKTE.md (Menschen, Aureas, Aureas-Kalender, Weltregeln, Aureas-Rätsel).
- [x] Lückenerkennung anhand des Volks-Steckbriefs und weiterer Pflichtangaben.
- [x] Impulse/Informationsstränge → KI-Vorschlag über OpenAI-kompatibles Gateway → atomare Übernahme; KI darf nur anlegen und leere Felder füllen.
- [x] Suche über alle Bereiche, Änderungsprotokoll, Löschschutz bei Verweisen, lokaler CSRF-/Host-Schutz.
- [x] 18 automatisierte Tests inkl. Migration, Spoiler-Kanarien, Atomarität und Ende-zu-Ende-Ablauf mit Fake-KI (Python 3.9 und 3.13).

## Erledigt: Erzählregeln und KI-Schnittstelle (2026-11-07)

- [x] `ERZAEHLREGELN.md` aus den Vorgaben des Nutzers angelegt (Einschlafgeschichten, Nachrichten im Untergrund, Zeit/Perspektive, Technik & Phänomene).
- [x] Bereich „Technik & Phänomene“ (Faltantriebe, Wurmlöcher, Türen …) mit Regeln & Grenzen und Lückenprüfung.
- [x] Folgen können Vorausblicke sein und auf eine andere Folge als Perspektive derselben Geschichte verweisen (Schema v3).
- [x] Impuls-Art `nachricht` für reale Nachrichten, die im Untergrund eingearbeitet werden.
- [x] KI-Vorschläge werden standardmäßig automatisch übernommen; Rückfragen halten sie zur Freigabe an (OFFENE_PUNKTE Nr. 7).
- [x] MCP-Server (stdio, ohne Zusatzpakete) für externe KI-Clients; Vorlage `mcp.example.json` für Claude Code.
- [x] Alte GSD-Planung nach `_old/` verschoben.

## Erledigt: Einstellungen, Themes, Sammelsurium (2026-11-07)

- [x] Einstellungsseite mit beliebig vielen KI-Anbietern, 12 Vorauswahlen inkl. OpenRouter, Anleitung je Anbieter.
- [x] Schlüssel prüfen, Modelle automatisch laden, manuelles Ergänzen nur optional; Archiv statt Löschen.
- [x] Modelle je Aufgabe mit 1./2./3. Wahl über Anbieter hinweg, automatischer Ausweich bei Ausfall, Test-Knopf.
- [x] Themes Hell, Dunkel, Bunt und eigenes Theme mit allen Funktionsfarben und Live-Vorschau.
- [x] Einschübe & Sammelsurium (Schema v4) als offener Pool, KI-Aktion zum Auffüllen.
- [x] Fehlerisolation: Vorschlags-Operationen einzeln, fehlerhafte werden übersprungen und gemeldet.

## Erledigt: KI-Läufe sichtbar machen (2026-11-07)

- [x] Dauerhaftes Protokoll je KI-Lauf (Schema v5): Auftrag, Weg mit Zeitstempeln, Fortschritt, Ergebnis, Modell, Dauer.
- [x] Fortschrittsbalken in der Kopfleiste und in der Laufansicht; Live-Antwort per Streaming (Backstage).
- [x] Ausweich auf 2./3. Wahl wird im Weg sichtbar protokolliert; MCP-Werkzeug `ki_laeufe`.

## Erledigt: Maßstab, Ortsbaum und Figuren entwickeln (2026-11-07)

- [x] Maßstab Atom … Galaxie (Schema v6): Orte liegen nur in größeren Orten, Ebene folgt aus der Art; Stränge und Ereignisse mit Maßstab.
- [x] Ortsbaum unter „Orte & Welten“; Ort-Ansicht zeigt alles im Ort und seinen Unterorten (Völker, Figuren, Firmen, Jobs, Stränge, Ereignisse …).
- [x] Firmen & Organisationen, Jobs & Laufbahn, Familie & Beziehungen (Schema v7); Figur-Ansicht mit Laufbahn, Familie, Geschichten und Wissen.
- [x] HTTPS funktioniert auch mit Python ohne eigene Stammzertifikate (Rückgriff auf Systemzertifikate).

## Erledigt: Folgen-Pipeline (2026-11-08)

- [x] Folgen erzeugen: Planer → Autor (kapitelweise) → Kontinuitätsprüfer → Lektor → Archivar (Schema v8).
- [x] Planer legt fehlende Figuren/Stränge selbst an; Einschübe aus dem Sammelsurium werden genutzt und als verwendet markiert.
- [x] Text im Format `[Sprecher] Text`, Segmente fürs Hörbuch, Export für das Audiobook Studio, Vorlesen im Browser.
- [x] Ende-Übergabe der letzten Folge fließt in den Anfang der nächsten; Zeit-Cursor des Strangs wird nachgezogen.
- [x] Fehlerisolation: Prüfer/Lektor/Archivar optional, Autor-Abbruch sichert Entwurf; alles im KI-Lauf protokolliert.
- [x] Neue Aufgaben „Folgen planen“ und „Archivar“ in Modelle je Aufgabe; MCP: folge_erzeugen, folgen_liste, folge_lesen.

## Neu: Menschen, Erzählprofil und Genres (Vorgabe des Nutzers, 2026-11-08)

Ziel: Die Geschichten sollen sich lesen, als kämen sie aus der Feder des Menschen, der Story World gerade nutzt –
und sie sollen nicht nur Sci-Fi können, sondern auch Krimi, Horror, Horror für Kinder usw. innerhalb der Welt.
Kein Login; nur eine Auswahl beim Start.

- [x] Beim Start fragen, wer gerade bedient: bekannte Menschen mit „zuletzt genutzt“ anklicken oder „Neuer Mensch“.
- [x] Interview für neue Menschen: indirekte, psychologisch gestellte Fragen (Lieblingsgeschichten, Umgang mit Konflikten,
      Humor, Tabus, Für-wen, Stilproben), damit Habitus und innere Motivation erfasst werden, die man selten selbst benennt.
- [x] Die KI verdichtet die Antworten zu einem Erzählprofil (Stimme, Satzbau, Wortwahl, Tempo, Humor, Motive, Werte, Tabus,
      Lieblingsgenres, innere Motivation) und stellt gezielte Nachfragen, wo es unklar bleibt. Keine Diagnosen – nur Erzählhaltung.
- [x] Profil ist sichtbar und von Hand änderbar; Interview jederzeit wiederholbar; entfernte Profile ins Archiv statt Löschen.
- [x] Profile liegen nur lokal (story_world.profiles.json, nur für dein Konto lesbar, per .gitignore ausgeschlossen); an die KI
      gehen sie nur beim Auswerten und beim Schreiben.
- [x] Genres als Bereich mit Regeln: Konventionen, Spannungsbogen/Tempo, Tabus, Ton und Altersfreigabe; Vorlagen für
      Science-Fiction, Krimi, Horror, Grusel für Kinder, Abenteuer, Drama, Komödie, Märchen.
- [x] Genre je Welt (Standard), je Strang und je Folge wählbar – z. B. ein Krimi oder Horror innerhalb der Sci-Fi-Welt.
- [x] Pipeline nutzt Profil und Genre: Planer (Motive, Genre), Autor und Lektor (Erzählstimme), Prüfer kontrolliert die
      Genre-Regeln.
- [x] Tabus bekommen eine Warnung statt einer Sperre, weil nicht jedes Modell mitmacht: Tabu-Befunde des Prüfers sind höchstens
      „mittel“, erscheinen als ⚠-Warnung an der Folge (Details nur ohne Spoilerschutz) und erzwingen keine Freigabe.
- [x] Verweigert ein Modell den Text (Absage statt Geschichte), springt automatisch die nächste Wahl des Autors ein; im KI-Lauf
      steht, welches Modell verweigert hat.
- [x] Altersfreigabe ist dem Autor (Nutzer) vorbehalten: Auswahl auf der Erstellungsseite, Genre-Vorgabe nur als Info,
      bei Fortsetzungen ist die Freigabe der letzten Folge vorausgewählt; der Prüfer bewertet sie nicht neu. Gespeichert je Folge.
- [x] Seite „Geschichten“: bestehende Geschichte weitererzählen (Karten mit Genre, Folgenzahl, letzter Folge, Weltzeit),
      neue Geschichte in einem Genre beginnen oder den Planer entscheiden lassen; ersetzt den Dialog „Neue Folge erzeugen“.
      Eine neue Geschichte behält ihr Genre für die folgenden Folgen.
- [x] Täglicher Lauf nutzt das Profil des Menschen, der die Welt zuletzt genutzt hat.
- [x] Eigene Seite je Mensch (👤 oben rechts): Einschätzung (Erzählprofil, Nachfragen, Modell/Datum), Befragung zum
      Nachlesen und Ändern, „Texte als Basis“.
- [x] Texte als Basis: einfügen oder Dateien hochladen (txt, md, html, docx, odt, epub, rtf; pdf mit pdftotext). Als Stilprobe
      markierte Texte fließen in die Profil-Auswertung ein. „In Welt einlesen“ zerlegt den Text in Abschnitte (~12.000 Zeichen)
      und lässt die KI daraus Kanon-Vorschläge machen (Impuls-Art „text“, Lauf „Text einlesen“); Abschnitte ohne Weltwissen
      werden übersprungen. Texte liegen lokal in profile_texte/ (nicht im Git), Archiv statt Löschen.
- [ ] Mit echtem Modell prüfen, ob Folgen hörbar nach dem Erzählprofil klingen; Fragen und Profilfelder danach nachschärfen.
      **Teilweise:** Ablauf mit simulierter KI getestet.

## Neu: Szenarien mit Abweichungsregler und Bewertung (Vorgabe des Nutzers, 2026-11-09)

Ziel: Die Schritte der Pipeline bekommen einstellbare Werte – wie kreativ (Temperatur) und wie weit sich die KI von der
Vorgabe entfernen darf (Abweichung). Statt einer Antwort liefert ein Schritt mehrere Szenarien. Ein eigener Bewerter
(anderer Agent, möglichst anderes Modell) misst je Szenario, wie gut es in den Kanon passt und wie groß die Überraschung
gegenüber dem ist, was der Hörer aus der bisherigen Geschichte erwartet. Gedacht vor allem für Genres wie intelligenten
Horror: Der Hörer glaubt sich auf der sicheren Seite und wird von der Handlung überrascht – ohne dass die Welt bricht.

- [x] Sofortkorrektur (Lauf #75): Planer-Prompt enthält das Operationsformat (`aktion`/`tabelle`/`ref`/`felder`) samt
      Beispiel für einen neuen Strang; `repair_payload` setzt englische/abweichende Schlüssel um; Fehlermeldung nennt den
      fehlenden Schlüssel.

**Ist-Stand:** Temperatur gibt es, aber fest (0,8 für alle Aufgaben, 0,4 fürs Erzählprofil, `providers.complete`). Einen
Wert für die Abweichung gibt es nicht. Jeder Schritt liefert genau eine Antwort, die nur auf Gültigkeit geprüft wird.

**Werte je Aufgabe** (Einstellungen → Modelle je Aufgabe; überschreibbar je Genre > Strang > Folge):

- Temperatur.
- Abweichung von der Vorgabe, Stufen 0–3: 0 eng am Plan und an der naheliegenden Fortsetzung · 1 Nebenwege erlaubt ·
  2 Wendung erlaubt · 3 Bruch mit der Erwartung. Wird im Prompt als konkrete Anweisung ausgedrückt, nicht nur über die
  Temperatur.
- Anzahl Szenarien (1–3; 1 = heutiges Verhalten).
- Ziel-Überraschung und Mindest-Kanonpassung (für die Auswahl).

**Ablauf** (zuerst beim Planer, weil ein Plan klein und günstig ist; Autor-Kapitel später):

1. **Erwartung:** Ein Agent sieht nur, was der Hörer kennt (bisherige Folgen, Übergabe, öffentlicher Kanon, kein Backstage)
   und schreibt in wenigen Sätzen, was er als Nächstes erwartet. Das ist die Messlatte für die Überraschung.
2. **Szenarien:** Der Planer liefert N Pläne mit unterschiedlicher Abweichungsstufe – standardmäßig in einem Aufruf, weil der
   Kontext (~350.000 Zeichen) der teure Teil ist; wahlweise getrennte Aufrufe oder verschiedene Modelle.
3. **Bewertung:** Ein Bewerter bekommt vollen Kanon inkl. Backstage, die Erwartung und die Szenarien und liefert je Szenario:
   Kanonpassung 0–10 (mit konkreten Widersprüchen), Überraschung 0–10 gegenüber der Erwartung, Fairness (Wendung vorher
   angelegt bzw. rückblickend erklärbar – „Überraschung ja, Betrug nein“) und eine kurze Begründung. Harte Prüfungen
   (Reisezeiten, tote Figuren, Wissensquellen, Zeitleiste) laufen zusätzlich per Code.
4. **Auswahl:** Szenarien unter der Mindest-Kanonpassung fallen raus; von den übrigen gewinnt das, dessen Überraschung am
   nächsten an der Zielvorgabe liegt. Automatisch oder als Auswahl für den Menschen (Karten mit beiden Werten).
5. **Weiter wie bisher:** Der Autor schreibt das gewählte Szenario. Verworfene Szenarien bleiben gespeichert (Backstage) und
   können später als Einschub oder Ripple wieder auftauchen.

**Was dazu angepasst werden muss:** Feste Vorgaben, die Abweichung heute verhindern, werden ab Stufe 2 gelockert statt
entfernt: „ehrlicher Erzähler“ → „täuschen erlaubt, aber auflösbar“; Pflicht-Anschluss an die vorige Folge → bewusster Bruch
erlaubt; Grundstil „hoffnungsvoll, Einschlafgeschichte“ gilt nicht mehr für jedes Genre; der Lektor bekommt Wendungsstellen
als „nicht glätten“. Fest bleiben: Spoilerschutz, Kanon-Sperre der Vergangenheit, Weltzeit ohne Tageszahlen, Wissen braucht
Quelle, Reisezeiten, Altersfreigabe durch den Menschen.

**Umsetzung (2026-11-09):**

- [x] Werte je Aufgabe: Temperatur unter „Modelle je Aufgabe“ (Experte); Überraschung (Abweichung 0–3), Anzahl Szenarien,
      Ziel-Überraschung, Mindest-Kanonpassung und „wer wählt“ unter „Diese Welt“; Überraschung zusätzlich je Genre, je Strang
      (Feld „Überraschung“) und je Folge (Seite „Geschichten“). Reihenfolge Folge > Strang > Genre > Welt.
- [x] Neue Aufgaben „Hörer-Erwartung“, „Szenarien bewerten“, „Qualitäts-Richter“ und „Thema wählen (Kaskade)“ in „Modelle je
      Aufgabe“; Bewerter und Richter laufen immer mit Temperatur 0.
- [x] Planer liefert `szenarien: [...]` mit Abweichungsstufen um die gewählte Stufe herum; ungültige Szenarien werden verworfen.
      Bewerter misst Kanonpassung, Überraschung und Fairness; Code zieht für tote Figuren und rückwärts laufende Zeit Punkte ab.
      Auswahl im Code (`szenarien.choose`).
- [x] Gelockerte Regeln ab Stufe 2: Erzähler darf fair in die Irre führen, Prüfer meldet das nicht als Erzähler-Problem,
      bewusster Bruch zur vorigen Folge erlaubt; Horror verliert den festen „hoffnungsvoll“-Grundton; Lektor bekommt die
      geplante Wendung als „nicht glätten“.
- [x] KI-Lauf zeigt Erwartung, alle Szenarien mit Werten und die Wahl; Speicherung je Folge (`scenario_sets`, Schema v12).
- [x] „Ich wähle selbst“: Szenarien warten auf der Seite „Geschichten“ (Titel, Idee, Kanon, Überraschung; Widersprüche und
      Begründung nur mit Backstage), ein Klick erzählt das gewählte Szenario.
- [ ] Später dasselbe Prinzip für Autor-Kapitel und Weltenbau (z. B. zwei Varianten eines neuen Volks).
- [x] Tests: Anzahl 1 ergibt das heutige Verhalten (bestehender Pipeline-Test); Erwartung sieht kein Backstage
      (Spoiler-Kanarie); Auswahl, eigene Wahl und Speicherung je Folge.
- [ ] Mit echten Modellen ausprobieren, ob die Überraschungswerte des Bewerters zum eigenen Hörgefühl passen; Zielwerte
      der Stufen (2 / 4 / 6,5 / 8,5) danach nachschärfen.

## Neu: Qualität der Modelle – Messung, Prüfstand, Vergleich, Kaskade (Vorgabe des Nutzers, 2026-11-09)

Ziel: merken, ob die Modelle noch im geplanten Rahmen arbeiten – auch wenn ein Anbieter sein Modell verändert oder ein anderes
Modell ausprobiert wird. Dazu Messwerte über die Zeit je Modell, eine feste Prüfwelt mit bekannten Antworten, Knöpfe zum
Gegeneinander-Antreten und ein schlankerer Kontext. Einfache Oberfläche für alle, Details hinter dem Schalter „Experte“.

- [x] G1: Jeder KI-Aufruf wird mit Prompt (komprimiert), Antwort, Modell, Dauer und Fehler gespeichert (`ai_calls`, Schema v12) –
      auch gescheiterte; die Rohantwort eines gescheiterten Planers bleibt erhalten.
- [x] G2: App-weite Messwert-Datenbank `story_world.qualitaet.sqlite3` (nicht im Git) mit Referenzwerten und Drift-Erkennung
      (`quality.py`).
- [x] G3: Prüfwelt (`pruefstand.py`): Figuren, toter Archivar, Fähre mit fester Reisezeit, Geheimnis mit Kanarienwort; wahlweise
      in eine Kopie der echten Welt eingebaut („Ballast“). Die echte Welt bleibt unberührt.
- [x] G4: Einstellungen → „Qualität der Modelle“: Ampel je Modell mit einem Satz (einfach); Tabelle je Test mit zuletzt, Mittel,
      Referenz, Verlauf, Status, „Stand als Referenz setzen“, Testerklärungen (Experte). Hinweis bei Modellwechsel.
- [x] G5: „Vergleichen“ an jedem KI-Aufruf eines Laufs: derselbe Prompt an bis zu drei Modelle, Original als Maßstab, Messwerte
      und optional Qualitäts-Richter (anonym A/B/C); Antworttexte nur mit Backstage. Prüfstand mit bis zu drei Modellen je Aufgabe.
- [x] Live-Messung je Folge (Code, kostenlos): 1 Format, 2 Länge, 3 Spoiler, 6 Wiederholung, 7 Kanon-Schaden, 8 Verweigerung,
      9 Konkretheit, 10 Stil, 14 Lektor-Schaden, K4 Kontextgröße; Werte auch an der Folge (Experte).
- [x] Prüfstand „schnell“: 4 Fallen für den Prüfer + Fehlalarme, 12 Archivar. „voll“: zusätzlich 1 Planer-Format, Autor
      (2, 3, 8, 9), 11 Plan-Treue, 15 Genre-Treue und 13 Streuung durch den Richter, 16 Bewerter-Rangfolge.
- [x] 5 Drift: Referenz = erste Messungen (oder per Knopf); weicht der Mittelwert der letzten zehn um mehr als die Toleranz ab,
      wird das Modell rot. Regelmäßiger Prüfstand alle n Tage (Qualität → Einstellungen, Standard aus).
- [x] K1–K3 Kaskade (`kontext.py`, Einstellung „Kontext“ unter „Diese Welt“, Standard „voll“): Thema aus kompaktem Überblick →
      Planer mit Datensätzen der Beteiligten → Autor nur mit Besetzung, Orten, Wissen bis zum Zeitpunkt; Prüfer und Archivar
      mit den im Text erwähnten Datensätzen, Archivar zusätzlich mit Namensverzeichnis gegen Doppelungen.
- [x] K4: Prüfstand mit Ballast einmal „voll“, einmal „Kaskade“ – Trefferquote und Kontextgröße stehen nebeneinander.
      In der Testwelt „erde“: Planer ≈ 355.000 Zeichen voll, ≈ 40.000 mit Kaskade.
- [x] 6 automatisierte Tests mit simulierter KI (Messwerte, Drift, Prüfstand mit Ballast und Kaskade, Szenarien, eigene Wahl,
      Aufruf-Speicher, Modellvergleich).
- [ ] Mit echten Modellen: ersten Prüfstand laufen lassen, Referenzen setzen, Grenzwerte (`quality.TESTS`) nachschärfen.
- [ ] Kaskade mit echten Modellen gegen den vollen Kontext messen und danach als Standard festlegen oder verwerfen.

## Nächste Schritte

- [x] Entfernungen zwischen Orten pflegen und Reisezeit je Antrieb/Phänomen berechnen (Welt → Entfernungen, Technik: Geschwindigkeit/Vorbereitung, Reiter „Zeit & Reisen“).
- [x] Nachrichtenquellen (RSS/Atom) anbinden: Abruf ohne Dubletten, neueste Meldungen als Impulse der Art `nachricht`.
- [x] Ripples (Wechselwirkungen zwischen Strängen): Archivar legt sie an, Planer greift fällige auf und hakt sie ab.
- [x] Täglicher Lauf per Zeitplan (eingebaut oder per launchd, siehe BETRIEB.md).
- [x] Hörbuch-Ausgabe für Einschlaf-Folgen: Vertonung mit macOS-Stimmen (.m4a), Player in der Leseansicht. **Teilweise:** ohne Musik/Mastering.

## MVP

Ein Abend funktioniert, wenn: eine Folge aus dem Kanon entsteht (Planer → Autor → Prüfer → Lektor → Archivar), sie ohne
Backstage-Wahrheiten lesbar und hörbar ist, der Kanon danach fortgeschrieben ist und Fehler einzelner Schritte die Folge
nicht verhindern. Nicht im MVP: Musik/Mastering, weitere Sprachen, Mehrbenutzerbetrieb.
Testfälle: Spoiler-Kanarien in allen Ausgabewegen, Figur an zwei Orten, unterschrittene Reisezeit, tote Figur in späterer
Folge, Kalender ohne Tageszahlen, Übergabe zwischen zwei Folgen, Rückblende mit damaligem Weltzustand, Ausweich-Modell,
Wiederherstellung einer Sicherung, Nachrichten ohne Dubletten.

## Noch nicht nachgewiesen

- [x] Ein erstes SQLite-Datenfundament und automatisierte Tests sind implementiert; eine laufende Pipeline und eine befüllte Datenbank sind noch nicht vorhanden.
- [x] Projektstatus: Dieser Plan ist die maßgebliche Übersicht (Oberfläche → Projektstatus). Die frühere GSD-Planung liegt in `_old/`.
- [x] `ERZAEHLREGELN.md` vorhanden. Eine detaillierte Stilrichtlinie (Erzählstimme, Satzbau) ist darin noch nicht festgelegt.

## Vorgeschlagener Stack

Für einen überschaubaren MVP werden **Python, SQLite, LiteLLM und Cron** vorgeschlagen: SQLite ersetzt PostgreSQL auf ausdrücklichen Wunsch und speichert den Kanon lokal. Python bündelt Pipeline und Prüfungen, LiteLLM kann Modellzugriffe vereinheitlichen, Cron den täglichen Lauf starten. LiteLLM und Cron sind noch nicht eingerichtet. Git dient der Versionierung; das Verzeichnis ist aktuell noch kein Git-Repository.

Orchestrierung zunächst als einfacher Python-Ablauf; LangGraph, Prefect oder n8n erst ergänzen, wenn Wiederaufnahme, Beobachtbarkeit oder komplexere Abläufe es erfordern. Für Retrieval Qdrant oder Chroma evaluieren und vor der Implementierung auswählen; die geforderte Vektorsuche entfällt dadurch nicht. TTS-Anbieter erst anhand von Stimmen, Sprache und Kosten auswählen. Dies sind technische Vorschläge, keine neuen Weltregeln.

## Meilensteine

### 0 – Grundlagen und Entscheidungen

- [x] Erzählregeln in `ERZAEHLREGELN.md` festgehalten; Stilrichtlinie im Detail noch offen, Stilkonformität daher nicht als geprüft ausgeben.
- [x] Antworten auf die sieben Fragen aus `OFFENE_PUNKTE.md` festhalten.
- [x] MVP-Abgrenzung und Testfälle: siehe Abschnitt „MVP“ unten; Tests in `tests/` (u. a. Spoiler-Kanarien, Reisezeit, tote Figuren, Übergabe).

**Ergebnis:** Ausreichend geklärte Vorgaben für einen ersten Probelauf; bewusst offene Punkte bleiben sichtbar.

### 1 – Kanon und Zeitmodell

- [x] SQLite-Schema und Migrationen aus `DATENMODELL.md` erstellen; Backstage-Daten von öffentlicher Ausgabe trennen.
- [x] Master-Weltzeit, Veröffentlichungsfolge, Strang-Cursor, Ereignisse und Wissensquellen modellieren.
- [x] Zeitbezogenen Weltzustand abrufbar machen (Zeitreise-Abfrage; Rückblenden/Vorausblicke bekommen beim Schreiben nur den damaligen Stand).
- [x] Kalenderumrechnung als Schnittstelle (Epoche, Jahreslänge, Zyklen, Jahres-/Zyklusnamen → „Jahr des …, zweiter Zyklus“); konkrete Namen füllt die KI über Lücken.
- [x] Reisen, Figurenstatus und Wissensstände mit Testdaten auf Konsistenz prüfen (automatische Prüfung im Reiter „Prüfung“).

**Ergebnis:** Nachvollziehbar speicherbarer und zeitbezogen abrufbarer Kanon.

### 2 – Text-MVP: eine Folge kontrolliert erzeugen

- [x] Planer, Autor, Kontinuitätsprüfer, Lektor und Archivar als nachvollziehbare Schritte; Prüfer bevorzugt ein anderes Modell als der Autor (Warnung, wenn keins da), Lektor nutzt nur seine 1. Wahl.
- [x] Ausgabe verarbeiten: Segmente (`[Sprecher]`-Format statt JSON, robuster bei langen Texten), Fakten, Rätsel-Status, Codes, Ripples und Übergabe über den Archivar.
- [x] Prüfungen für Ortsüberschneidungen, Reisezeiten, Wissensquellen (Quelle ist Pflicht) und tote Figuren; Erzähler-Ehrlichkeit prüft der Kontinuitätsprüfer.
- [x] Änderungen erst als Vorschlag speichern, prüfen, dann übernehmen. Auf Wunsch des Nutzers wird jede Operation einzeln übernommen: Eine fehlerhafte wird übersprungen, statt alles zu blockieren.
- [x] Zwei aufeinanderfolgende Testfolgen mit Übergabe erzeugen und ohne Backstage ausgeben (automatisierter Test mit simulierter KI). **Teilweise:** mit echtem Modell noch nicht durchlaufen.

**Ergebnis:** Ein kontrollierter Text-Probelauf mit nachvollziehbarer Prüfung und Übergabe; noch kein unbeaufsichtigter Dauerbetrieb.

### 3 – Fortlaufende Welt und Automatisierung

- [x] Offene Ripples, lange offene Rätsel und Konsistenzprobleme fließen in die Planung. **Teilweise:** Wechselwirkungen der Ebenen nur mit simulierter KI getestet.
- [x] Weltentwicklung: Nach jeder Folge bekommen bis zu drei abwesende Völker 1–2 Entwicklungen als Backstage-Ereignisse (eigener KI-Lauf).
- [x] Folgenzusammenfassungen und Fakten für Retrieval indexieren; zeitlich und hinsichtlich Spoilerschutz filtern (lexikalisch mit SQLite FTS5; Vektorsuche später optional).
- [x] Täglicher Zeitplan mit Fehlerprotokoll (KI-Läufe), Nachholen am selben Tag und Schutz gegen doppelte Läufe.
- [x] Gezielte Freigabe nur bei schweren Prüfer-Befunden oder Rückfragen; Kanon-Score, Erzähler-Hinweise und Code-Wiederholungen je Folge.
- [ ] Mehrere Folgen über parallele Stränge und mindestens eine Rückblende hinweg testen. **Teilweise:** Rückblende mit simulierter KI getestet; echte Folgen stehen aus.

**Ergebnis:** Über mehrere Tage betreibbare, überprüfbare Textpipeline.

### 4 – Hörbuch

- [x] Segmentiertes JSON für TTS/Studio (Export je Folge); feste Stimme für den Erzähler, Figuren über „Stimme (Hörbuch)“.
- [x] Aussprache-Lexikon, Kalendernamen im Erzähltext, Folgenlänge ~60 Minuten (8000 Wörter einstellbar), Deutsch. **Teilweise:** weitere Sprachen noch nicht.
- [ ] Leitmotive, Klangbild für Rückblenden und automatisches Mastering integrieren.
- [ ] Inhaltliche Überlappung zwischen Folgen sowie Audioqualität prüfen. **Teilweise:** Übergabe fließt in den Autor und wird vom Prüfer kontrolliert; Audioqualität offen.

**Ergebnis:** Durchgängiger Export einer geprüften Folge als Hörbuch.

### 5 – Abnahme und Betrieb

- [ ] Spoilerschutz, Zeitreisen-Abfragen, Kalender, Reise- und Wissensregeln sowie Fehlerfälle Ende-zu-Ende prüfen.
- [ ] Modellwechsel auf Stilbrüche prüfen. **Teilweise:** Sicherung und Wiederherstellung (als neue Welt) sind umgesetzt und getestet.
- [x] Betriebsablauf und Freigabe dokumentiert (BETRIEB.md); Begleitheft erst nach Entscheidung.

**Ergebnis:** Abgenommener Betrieb mit nachvollziehbaren Qualitäts- und Wiederherstellungsprüfungen.

## Abhängigkeiten und Entscheidungen

1. Die fehlenden Erzählregeln begrenzen Stilvorgaben und Erzähler-Ehrlichkeitsprüfung.
2. Zunächst Deutsch und ungefähr 60 Minuten pro Hörbuchfolge sind festgelegt; weitere Sprachen sollen später möglich sein. Freigabe erfolgt gezielt bei wichtigen Entscheidungen oder Problemen.
3. Das System soll Kalendernamen und Feste entwickeln; Umrechnung und Ausgabe benötigen vor produktivem Einsatz konkrete Daten.
4. Die getroffenen Entscheidungen zu Welterschaffung, Rätseln, Ton und optionalem Glossar stehen in `OFFENE_PUNKTE.md`. Keine Geheimnisse oder Auflösungen vorwegnehmen.

**Empfohlener nächster Schritt:** Fehlende Erzählregeln bereitstellen beziehungsweise klären; danach mit Meilenstein 1 beginnen.
