# Änderungen

Jede Version hat einen Abschnitt `## X.Y.Z – Kurztitel`. Nach einem Update zeigt Evel • Rote Fäden die Abschnitte
seit der zuletzt genutzten Version als Hinweis an (auch nach manuellem ZIP-Entpacken).

## 0.1.0 – Update-Knopf
- Einstellungen → Update: neue Versionen direkt von Codeberg laden und installieren.
- Nur Programmdateien werden ersetzt; Welten, Einstellungen, Profile, Stimmen, Texte und Exporte bleiben unberührt.
- Alte Programmdateien landen in `_old/update-…`, nichts wird gelöscht. Bei einem Fehler wird der alte Stand wiederhergestellt.
- Nach dem Neustart: Hinweis, was neu ist und welche Welten auf ein neues Datenbankschema gebracht wurden (mit Sicherung).
