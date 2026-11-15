# Änderungen

Jede Version hat einen Abschnitt `## X.Y.Z – Kurztitel`. Nach einem Update zeigt Evel • Rote Fäden die Abschnitte
seit der zuletzt genutzten Version als Hinweis an (auch nach manuellem ZIP-Entpacken).

## 0.3.0 – Mit ChatGPT-Abo anmelden
- Neuer KI-Anbieter „ChatGPT-Abo (Plus/Pro)“: Einstellungen → KI-Anbieter → „+ Anbieter hinzufügen“ → „Continue with ChatGPT“. Anmeldung im Browser, kein API-Schlüssel nötig; die Modelle werden danach automatisch geladen.
- Die KI-Anfragen zählen auf das Kontingent deines ChatGPT-Abos. Wie viel diese App nutzen darf, stellst du in ChatGPT ein (Einstellungen → Nutzung). Ist das Limit erreicht, springt die 2./3. Wahl der Aufgabe ein.
- Die Anmeldung erneuert sich selbst; „Abmelden“ beendet sie auch bei OpenAI. Die Zugangsdaten bleiben auf deinem Rechner.
- Neue README.

## 0.2.0 – Update abgesichert
- Wird ein Update hart unterbrochen (z. B. Stromausfall), stellt der nächste Start den vorherigen Stand automatisch wieder her und zeigt einen Hinweis.
- Braucht eine neue Version ein neueres Python, wird sie nicht installiert – mit verständlichem Hinweis statt eines kaputten Programms.
- Notfall-Rückweg: `python3 -m story_world update --zurueck` holt den Stand vor dem letzten Update zurück und nennt die passenden Welt-Sicherungen.
- Listen: Klick auf einen Spaltenkopf sortiert (auf-, absteigend, aus); Filterfeld über jeder Bereichsliste und über längeren Tabellen.
- Figuren: Vorname, Nachname und Geschlecht; die Liste zeigt Vorname, Nachname, Geschlecht und Volk. Bestehende Namen werden beim ersten Öffnen aufgeteilt (mit Sicherung).
- Familie & Beziehungen: Liste mit „Vorname Nachname → Vorname Nachname“, neue Felder Grund der Verbindung, Bruch (Weltzeit) und Grund des Bruchs; das Formular zeigt oben im Klartext, wer mit wem verbunden wird.
- Beziehungsnetz: In „Figuren“ und „Familie & Beziehungen“ per „◉ Netz“ umschalten. Familien liegen je in einem Kreis, weitere Beziehungen verbinden quer (gebrochene rot gepunktet). Bubbles mit Vor- und Nachname, Farbe = Volk; Klick öffnet Figur bzw. Beziehung, Ziehen verschiebt, Mausrad zoomt. Auf der Figurenseite zeigt „◉ Im Netz“ die Figur mit ihren Verbindungen.
- Schreibstil: Jede Stimme lässt sich einzeln exportieren („⇩ Exportieren“ an der Stimme) und über „⇧ Schreibstil importieren“ wieder einlesen – auch auf einem anderen Rechner. Vorhandene Stimmen werden nie überschrieben: Ist der Name schon vergeben, bekommt die importierte Stimme eine Ziffer („Leise 2“). Probe-Audio gehört zum Rechner und wird dort neu erzeugt.
- Geschichte wählen: Oben steht der Creator (Grundlage wählen: Planer, bestehende Geschichte oder neues Genre, dann Einstellungen und „Folge erzeugen“). Darunter die Geschichten als sortier- und filterbare Liste; ein Klick öffnet ein Fenster mit Inhalt, Figuren, Orten, letzter Folge und „So geht es weiter“ – und „Davon eine weitere Folge“. Genres ebenfalls als Liste darunter.
- Neue Welt aus einem Buch oder einer Geschichte (Datei): wählbar „Welt damit starten“ (Welt darf wachsen) oder „Fortsetzung“ (Welt bleibt beim Buch, Folgen setzen am Ende an) und „im Genre bleiben“ oder „Genre frei“. Die KI liest die Vorlage abschnittsweise ein und erstellt einen Steckbrief (Genre, Zusammenfassung, Stand am Ende, offene Fäden, Haupthandlung). Modus und Genre gelten in jedem KI-Aufruf der Welt; bei festem Genre ist es im Creator gesperrt.

## 0.1.0 – Update-Knopf
- Einstellungen → Update: neue Versionen direkt von Codeberg laden und installieren.
- Nur Programmdateien werden ersetzt; Welten, Einstellungen, Profile, Stimmen, Texte und Exporte bleiben unberührt.
- Alte Programmdateien landen in `_old/update-…`, nichts wird gelöscht. Bei einem Fehler wird der alte Stand wiederhergestellt.
- Nach dem Neustart: Hinweis, was neu ist und welche Welten auf ein neues Datenbankschema gebracht wurden (mit Sicherung).
