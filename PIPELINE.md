# Pipeline (täglich, per Scheduler)

1. **Planer-Agent**: Strang wählen, Weltzustand zum Cursor abrufen, offene Ripples/Rätsel/Codes prüfen, Outline erstellen. Vorgaben pro Folge, z. B.
   "ein Code wiederholen, einen Hinweis säen, Ende als Übergabe".
2. **Autor** (beliebiges Modell über Gateway): schreibt nach Prompt aus
   Stilrichtlinie, Story-Bible-Auszug, Folgenübergabe, Outline.
   Ausgabe als JSON.
3. **Kontinuitätsprüfer** (anderes Modell): Widersprüche, Zeit, Wissen,
   Erzähler-Ehrlichkeit.
4. **Lektor** (immer dasselbe Modell): vereinheitlicht Stil.
5. **Archivar**: extrahiert Fakten, Events, Ripples und neue Cursor-Position zurück
6. **Freigabe**: optional menschlich (wöchentlich oder bei Wendepunkten).
7. **Export** an Hörbuch-Pipeline.

## Ausgabeformat des Autors (JSON)
{
  "titel": "...",
  "text": "...",
  "segmente": [
    {"typ": "narrator|character", "sprecher": "...", "text": "..."},
    ...
  ],
  "neue_fakten": [],
  "neue_raetsel": [],
  "codes_verwendet": [],
  "ripples": [],
  "ende_uebergabe": {}
}

## Empfohlener Stack (änderbar mit Begründung)
- Orchestrierung: Python + LangGraph/Prefect oder n8n
- Modell-Gateway: LiteLLM oder OpenRouter (Fallbacks)
- Datenbank: Postgres
- Vektor-DB: Qdrant oder Chroma
- Versionierung: Git
- Scheduler: Cron
- Standardisieren: Temperatur, Länge, Ausgabeformat

## Qualitätsmaße
- Kanon-Score (verletzte Fakten pro Folge)
- Erzähler-Ehrlichkeits-Check
- Code-Wiederholungszähler
