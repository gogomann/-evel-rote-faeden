# ![icon](Logo/favicon/favicon-32x32.png) evel rote Fäden. Das Ende gefällt dir nicht?
Dann schreib es weiter.

Deine Lieblings Story Endet nicht wie **Du** es willst naja, lass es sich selbst Entwikeln. So das es für **Dich** ganz Neu ist.


Ein Programm, das mit dir Geschichten, Serien und Hörbücher schreibt – und dabei lernt, wie *du* erzählst.

## BYOK
Das Programm ist BYOK (Bring Your Own Key), also damit entschiden Sie ob local oder Online LLM Sie nutzen. By OpnAi ist auch der OAuth möglich. 

---
## install
es braucht nur [python](https://www.python.org/downloads/)  Version Python 3.15 oder höher. 

### Mac & Linux
Mac run `bash brew install python`  
Kontrolle run `bash python3 --version`

### Windwos
Install [Python install manager](https://www.python.org/downloads/release/pymanager-264/)

## ✨ Was es kann

| | |
|---|---|
| 🧠 **Lernt dich kennen** | Dein Konto merkt sich deinen Humor, deine Vorlieben, deinen Schreibstil und deine Lieblingsautoren. |
| 🌍 **Welten anlegen** | Baue eigene Welten – oder nimm ein Buch als Grundlage und mach daraus eine Serie oder gib der Geschichte eine neue Richtung. |
| 📚 **Kanonische Folgen** | Folgen und Geschichten bauen sauber aufeinander auf. Nichts widerspricht sich. |
| 🔍 **Lücken finden & lösen** | Die KI erkennt offene Stellen in deiner Welt und schlägt Lösungen vor. |
| 👥 **Figuren, die wachsen** | Figuren entwickeln sich weiter – automatisch per KI oder von dir gesteuert. |
| 🎭 **Viele Genres, eine Welt** | In derselben Welt mehrere Genres: In der Sci-Fi-Welt auch mal eine Liebesgeschichte oder einen Krimi. |
| ⏱️ **Länge frei wählbar** | Du bestimmst, wie lang eine Folge oder Geschichte wird. |
| 🧩 **Rätsel & Plot-Twists** | Geschichten mit Rätseln oder überraschenden Wendungen erstellen. |
| 🎙️ **Export fürs Hörbuch** | Export für Text-to-Speech – als SSML oder als Rollentexte. So bekommt jede Figur ihre eigene Stimme. |
| 🎭 **Hörspiel mit Libra-TTS** *(Zusatzfunktion)* | Eigener Sprach-Server, offline: 8 Stimmen, Sprechstile (warm, traurig, flüsternd …) und Geräusche (Seufzen, Lachen, Atmen). Die KI führt Regie, du kannst jeden Absatz einzeln anhören und neu aufnehmen. |
| 🔌 **MCP-Schnittstelle** | Andere Programme greifen auf deine Weltdaten zu – z. B. für Comics – oder entwickeln Geschichten und Folgen weiter. |

---

## 🚀 Loslegen

1. **ZIP herunterladen:** [github.com/gogomann/-evel-rote-faeden](https://github.com/gogomann/-evel-rote-faeden) → „Code“ → „Download ZIP“ bzw. unter „Releases“
2. **Entpacken** – immer in denselben Ordner.
3. **Starten.** Beim ersten Start prüft das Programm, ob Zusatzprogramme fehlen (z. B. für den MP3-Export), und bietet an, sie zu installieren.

> **Zusatzfunktion Libra-TTS (optional) – größerer Download, nur einmal**
> Beim ersten Start fragt Evel, ob der mitgelieferte Sprach-Server **Libra-TTS** eingerichtet werden soll (Hörspiel-Stimmen mit Sprechstilen und Geräuschen, offline).
> Dafür werden **einmalig ca. 1,3 GB auf einem Mac mit Apple-Chip, ca. 2 GB auf Windows/Intel-Mac (Prozessor), mit NVIDIA-Grafikkarte bis ca. 4 GB** geladen – Sprachmodell von Hugging Face (huggingface.co/Ekam/Libra-TTS), Python-Pakete von pypi.org (mit NVIDIA-Grafikkarte zusätzlich PyTorch von download.pytorch.org).
> Das passiert nur beim Einrichten, nicht bei Updates. Danach ist Libra automatisch eingebunden und startet mit Evel. Braucht Python 3.10 oder neuer.
> Du kannst ablehnen und es später unter **Einstellungen → TTS-Server → „Einrichten“** nachholen. Evel funktioniert auch ohne.

Updates kommen per Knopfdruck direkt in der App.

Keine Programmierkenntnisse nötig.

## unter der Motorhaube
ZEIT_UND_STRAENGE.md
## für die mehr wissen wollen

Story World:  
[Die Architektur](https://github.com/gogomann/-evel-rote-faeden/blob/main/architektur.html)   
[SQLite-Kernschema](https://github.com/gogomann/-evel-rote-faeden/blob/main/datenbankschema.html)  
[Systemübersicht](https://github.com/gogomann/-evel-rote-faeden/blob/main/systemuebersicht.html)  
[KI-Live-Datenfluss](https://github.com/gogomann/-evel-rote-faeden/blob/main/event-stream.html)  
[KI-Aufruf und Korrekturschleife](https://github.com/gogomann/-evel-rote-faeden/blob/main/ki-aufrufschleife.html)  

[So entsteht eine Folge](https://github.com/gogomann/-evel-rote-faeden/blob/main/prozess.html)  
[Vom Wunsch zur Geschichte](https://github.com/gogomann/-evel-rote-faeden/blob/main/user-journey.html)  
