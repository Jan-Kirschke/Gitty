# Gitty

Gitty ist ein kleiner Terminal-Messenger mit Zeitstempeln und einer `users`-Liste. Der Server lauscht standardmäßig auf TCP-Port `5555`.

Der PyPI-Projektname ist `gitty-messenger`, weil `gitty` bereits von einem anderen Projekt verwendet wird. Der Befehl bleibt `gitty-client`.

## Schnellstart auf dem Raspberry Pi

```bash
git clone https://github.com/Jan-Kirschke/Gitty.git
cd Gitty
docker compose up -d --build
docker compose logs -f gitty
```

Der Server ist danach unter `<IP-des-Pi>:5555` erreichbar, zum Beispiel `192.168.178.25:5555`, falls diese IP stimmt.

Status und Stoppen:

```bash
docker compose ps
docker compose down
```

## Client ohne Repository-Klon

Auf jedem Client-Gerät genügt:

```bash
python -m pip install gitty-messenger
gitty-client <IP-des-Pi> -p 5555
```

Im Client zeigt `users` die aktuell verbundenen Benutzer. Nachrichten werden mit ihrem Zeitstempel angezeigt.

## In ein bestehendes Compose-Projekt aufnehmen

Das Image einmal im geklonten Gitty-Verzeichnis bauen:

```bash
docker build -t gitty:local ~/Gitty
```

Danach aus dem Verzeichnis des bestehenden Compose-Projekts starten:

```bash
docker compose -f docker-compose.yml -f ~/Gitty/compose.gitty.yml up -d gitty
```

Den Pfad `~/Gitty` bei Bedarf anpassen. `compose.gitty.yml` ergänzt dort den Dienst `gitty` und veröffentlicht Port `5555`.

## Neue Version auf PyPI veröffentlichen

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

Für den Upload brauchst du einen PyPI-Account und einen API-Token. Den Token nicht ins Repository committen.

Gitty ist für Tests im lokalen Netzwerk gedacht. Port `5555` nicht ins Internet weiterleiten.
