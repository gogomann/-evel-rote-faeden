# Änderungen

Jede Version hat einen Abschnitt `## X.Y.Z – Kurztitel`. Nach einem Update zeigt Evel • Rote Fäden die Abschnitte
seit der zuletzt genutzten Version als Hinweis an (auch nach manuellem ZIP-Entpacken).

## 0.6.2 – Stil-Abgleich mit fremdsprachigem Vorbild
- Fehler behoben: Stammt das Vorbild aus einem Buch in einer anderen Sprache (z. B. die englische Ausgabe von „The Three-Body Problem“), wurde eine deutsche Folge trotzdem an Wortlänge, Wortvielfalt, Kommas und den deutschen „kleinen Wörtern“ gemessen. Das ergab unsinnige Abweichungen („‚die‘ häufiger“, Autorensignatur 20,99) und eine viel zu schlechte Stil-Treue.
- Evel erkennt jetzt die Sprache von Vorbild und Folge (auch bei schon gespeicherten Fingerabdrücken). Bei unterschiedlicher Sprache werden nur Satzbau, Rhythmus, Dialoganteil und Satzzeichen verglichen; der Abgleich sagt dazu, was nicht vergleichbar ist. „Auffällig oft benutzt“ entfällt dann.
- Auch die Stilziele für Planer, Autor und Lektor übernehmen aus einem fremdsprachigen Vorbild keine Wortlänge und Kommasetzung mehr.
- Bereits gemessene Folgen: unter „Stil-Abgleich“ über „vergleichen mit“ neu messen.

## 0.6.1 – Vertonung nicht doppelt starten
- Fehler behoben: Wurde „Neu vertonen“ zweimal kurz hintereinander gestartet (z. B. Doppelklick), liefen zwei Vertonungen derselben Folge gleichzeitig, schoben sich gegenseitig die Datei weg und brachen mit „No such file or directory“ ab.
- Jetzt läuft je Folge höchstens eine Vertonung; ein zweiter Start bekommt sofort den Hinweis „wird gerade schon vertont“. Der Knopf ist nach dem Klick gesperrt.

## 0.6.0 – Systemprüfung beim Start
- Beim ersten Start nach dem Entpacken (und nach jedem Update) prüft Evel, ob die Zusatzprogramme da sind: MP3-Encoder (lame oder ffmpeg) und auf dem Mac die Systemstimmen.
- Fehlt der MP3-Encoder, fragt das Startfenster, ob er automatisch installiert werden soll – Enter genügt. Mac: über Homebrew (`lame`), Windows: über winget (FFmpeg). Geht das nicht, steht im Fenster, was zu tun ist.
- Gefragt wird nur einmal je Version; danach erscheint nur ein kurzer Hinweis. Erneut prüfen und installieren: `python3 -m story_world system`.
- Mac-Startdatei prüft jetzt auch, ob Python 3.9 oder neuer vorhanden ist (wie schon unter Windows).
- Die Prüfung hält den Start nie auf: Ohne Encoder läuft alles wie gehabt, Vertonungen kommen dann als WAV/M4A.

## 0.5.0 – Vertonung als MP3
- Vertonungen (TTS-Server und macOS-Stimmen) werden als MP3 gespeichert – mit ausgefüllten ID3-Tags: Titel („Folge 3: …“), Album (Welt – Strang), Album-Interpret (Welt), Interpret (Stimmen), Tracknummer (Folgennummer), Jahr, Genre (Hörspiel/Hörbuch), Gruppierung (Genre der Folge), Sprache, Länge und Zusammenfassung als Kommentar. So sortieren Musik-Apps, Plex & Co. die Folgen richtig ein.
- Braucht `lame` oder `ffmpeg` auf dem Rechner (Mac: `brew install lame`). Fehlt beides, bleibt es wie bisher bei WAV bzw. M4A.
- Die WAV-Datei bleibt erhalten und liegt danach im Unterordner `_wav`; ältere MP3s wandern nach `_alt`.
- An der Folge heißt der Knopf jetzt „MP3 herunterladen“.

## 0.4.0 – Stil-Fingerabdruck
- Schreibstil: Eine Stimme „wie ein Autor“ kann jetzt ein Buch dieses Autors als Referenz bekommen (unter „👤 Mensch → Texte als Basis“ einfügen, als „fremd“ markieren, dann an der Stimme anhaken). Evel misst daraus den Stil-Fingerabdruck: Satzlänge, Rhythmus, sehr kurze und lange Sätze, Verschachtelung, Dialoganteil, Wortlänge, Wortvielfalt, Erzählzeit, Perspektive, Satzzeichen und die „kleinen Wörter“ (und, doch, noch …), an denen man Autoren erkennt – jeweils mit der Spanne, in der der Autor selbst schwankt. Gemessen wird per Code, ohne KI; der Buchtext geht nie an die Schreib-KI.
- Auch eigene Texte („wie Ralf“) und freigegebene Proben liefern einen Fingerabdruck (aus einer kurzen Probe nur geschätzt – das steht dann dabei).
- Planer, Autor und Lektor bekommen den Fingerabdruck als messbare Stilziele („im Schnitt 9 Wörter je Satz, Präteritum, dritte Person …“), der Prüfer ebenso.
- Jede neue Folge wird danach Merkmal für Merkmal mit dem Vorbild verglichen: an der Folge unter „Stil-Abgleich“ (Folge gegen Vorbild, normale Spanne, was abweicht, auffällig oft benutzte Wörter) und im KI-Lauf. Weicht sie deutlich ab, wartet sie auf deine Freigabe – abschaltbar unter Einstellungen → Diese Welt → Stil-Abgleich.
- Ältere Folgen lassen sich nachträglich messen, auch gegen eine andere Stimme („vergleichen mit“).
- „Wessen Stil ist das?“ auf der Seite Schreibstil: Text einfügen, Evel zeigt, welcher Stimme er am nächsten kommt.

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
