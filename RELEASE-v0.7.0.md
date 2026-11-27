⚠️ WICHTIG – NEUE ZUSATZFUNKTION MIT GRÖSSEREM DOWNLOAD (optional, nur einmal)

Evel bringt jetzt einen eigenen Sprach-Server für Hörspiele mit: Libra-TTS – Stimmen mit Sprechstilen und Geräuschen, offline auf deinem Rechner.

Das Update selbst ist klein. Wer Libra einrichtet, lädt EINMALIG:
• Mac mit Apple-Chip: ca. 1,3 GB
• Windows / Intel-Mac (Prozessor): ca. 2 GB
• mit NVIDIA-Grafikkarte: bis ca. 4 GB

Quelle:
• Sprachmodell: Hugging Face – huggingface.co/Ekam/Libra-TTS
• Python-Pakete: pypi.org (mit NVIDIA-Grafikkarte zusätzlich PyTorch von download.pytorch.org)

Der Download startet erst, wenn du zustimmst: beim nächsten Start im Startfenster („J“) oder später unter Einstellungen → TTS-Server → „Einrichten“. Spätere Updates laden das nicht erneut. Danach ist Libra automatisch eingebunden: startet und beendet sich mit Evel und steht unter TTS-Server bereit. Braucht Python 3.10 oder neuer. Evel funktioniert auch ohne.

Neu in 0.7.0
• Libra-TTS mitgeliefert (zusatz/libra-tts): 8 Stimmen, 12 Sprechstile, Geräusche wie <sigh>, <laugh>, <breath>.
• Hörspiel-Regie: Die KI legt je Absatz Sprechstil, Stilwechsel (z. B. dokumentarisch bei Zahlen) und Geräusche fest; Atmer setzt Evel selbst. Stufe je Folge: aus, dezent, lebendig. Der Folgentext bleibt unverändert.
• Regie-Editor (Expertenmodus): Geräusche und Stilwechsel per Klick, Tempo von Hand, Sprechtext fürs Hörspiel umformulierbar (der lesbare Text bleibt im Original), alles speichert automatisch.
• Jeden Absatz einzeln anhören (▶/⏸), neu aufnehmen (🔁) und Takes tauschen – erst „Hörspiel zusammenfügen (MP3)“ baut die Datei, ohne Bereits-Gesprochenes neu zu sprechen.
• JSON-Export: Text so wie gesprochen (mit Geräuschen), Stil, Stilwechsel-Teile und bei Umformulierungen der Originaltext.
• Update-Dialog zeigt besonders wichtige Hinweise einer neuen Version groß an.
