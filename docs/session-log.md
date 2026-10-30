# Session Log — Bitácora

Chronological log of every work session. A new entry is added at the start of
each session and filled in real time as work progresses. **Newest entry on top.**

Entry format:
```
## YYYY-MM-DD — [brief session title]
**Time:** HH:MM (aprox)
**User request:** ...
### Actions taken
- ...
### Decisions
- ...
### Outcomes
- ...
### Next steps / open questions
- ...
```

---

## 2026-10-30 — rapa-nui.yaml sincronizado otra vez con la plataforma
**Time:** 19:05 (aprox)
**User request:** copiar aquí el `.yaml` de la plataforma.

### Actions taken
- Copiado `deployments/rapa-nui.yaml` de la plataforma (commits `9d17270` y
  `6d161b0`) a `deployments/sasipa/rapa-nui.yaml`, byte a byte (sha
  `01a9376b…`). El gateway lo lee; 278 tests OK.

### Outcomes
- GW (`!6c74104c`), D1 (`!6c72f308`) y D2 (`!6c743130`) ya tienen `node_id`:
  el receptor reconoce la radio de pi7 y acepta mensajes enviados desde D1/D2.
  D1 y D2 declaran `position: 900`, así que su entrega se mide una vez oídos.
- N3 queda sin `node_id` (la plataforma aún no sabe qué caja es N3): si
  transmitiera, se descartaría como remitente desconocido y no tendría marcador
  más que el planificado.
- Campos nuevos (`firmware`, `site.name`, `asset_code`, `asset_type`, `notes`):
  el gateway no los lee.

---

## 2026-10-30 — Preparación de la prueba local de rapa-nui en la oficina
**Time:** 12:30–13:00 (aprox)
**User request:** probar rapa-nui en la oficina con el yaml actualizado de la
plataforma (revisarlo y traerlo), el punto de acceso de pi7 y 5 nodos: N3
(`!32fe0d4e`) sigue en el campus y no transmitirá.

### Actions taken
- Revisado el `rapa-nui.yaml` de la plataforma (commit `52ed4dd`): fibra de
  vidrio en N2, N5 y N6; `tx_power_policy: declared`, que acepta los 30 dBm con
  advertencias (el firmware los recorta a 22). `validate` ✓. Copiado aquí
  (sha `c7475ffd…`); el gateway lo lee (ignora `tx_power_policy`).
- Comprobado: el receptor solo mide la entrega de un flujo ya oído, así que N3
  no genera pérdidas ni alarmas; el `.env` de la plataforma tiene
  `EASTERNET_TELEMETRY_PSK` y `EASTERNET_MSG_PSK` (solo nombres).
- Mapa: si los sitios no caben en una vista (un nodo con GPS en la oficina y el
  resto planificados en la isla), muestra donde está la mayoría y avisa cuántos
  quedan fuera; antes se centraba en el océano vacío entre ambos.
  `getBoundsZoom` no sirve para detectarlo: recorta al zoom mínimo. Probado en
  Chrome headless.

### Next steps / open questions
- GW, D1 y D2 sin `node_id`: el receptor avisará que la radio de pi7 no está en
  el archivo (inofensivo). Un mensaje desde un nodo sin `node_id` se descarta
  como remitente desconocido: para probar mensajes, desde un nodo registrado o
  con el ID de D1 en el yaml.

---

## 2026-10-30 — Mensajes de texto en el dashboard
**Time:** 11:00–12:15 (aprox)
**User request:** "uno de los requisitos principales": un canal donde ver los
mensajes de texto que recibe un nodo. Además, acortar la descripción del grafo
a "SASIPA network".

### Actions taken
- Descripción: `meta.description: SASIPA network` en el `rapa-nui.yaml` de la
  plataforma (copia idéntica aquí, sha `c14aba35…`); bajo el título del grafo
  solo la descripción, y la radio en el tooltip de la etiqueta de la malla.
- Hallazgos antes de cambiar: G12 dejaba los mensajes fuera del canal en vivo
  (teléfonos del PBX) y el texto nunca se publicaba; además todo
  `TEXT_MESSAGE_APP` se leía como trama del PBX, así que un texto de la app
  Meshtastic (vía D1/D2) salía "malformed".
- Decisiones del usuario: mostrar los de la app Meshtastic y los del PBX;
  guardar el texto en InfluxDB; teléfonos enmascarados.
- `gateway/payload.py`: `origin` (`pbx` | `meshtastic`), `text` (o
  `content_hex` si no es UTF-8); texto de app = no es trama del PBX, UTF-8, no
  empieza con carácter de control; `dst_id` del nodo destino, `null` en
  difusión. Se quitó `capture_content`. El receptor también registra en la
  terminal los textos de la app.
- Telegraf: medición `message` (antes `pbx_message`), tag `origin`,
  `json_string_fields = ["text", "content_hex"]` (sin eso los descarta).
- ACL: `monitor` lee también `{prefix}/+/message`. `monitor/utils.py`:
  `mask_phone()`/`for_browser()` (+56 •••••6789) en la API y en el canal en
  vivo; `get_messages()` (de/para un nodo, lo más nuevo primero).
- `gateway/deployment.py`: nombres de canal (`radio.channels`).
- `/messages` + `/api/messages`: pestaña Messages (vista tipo canal, en vivo,
  filtro por nodo, nombre del canal, SNR/RSSI/hop); enlace desde el dashboard
  de cada nodo.
- `docs/design.md`: contrato del payload de mensajes, medición `message`,
  cuenta `monitor` y G12 reescrito ("ningún teléfono llega entero a un
  navegador").

### Outcomes
- Consulta de mensajes probada contra un InfluxDB 1.8 local (filtro de/para,
  texto con tildes y comillas, enmascarado). Página revisada a 911×512.
  278/278 tests.

### Next steps / open questions
- En pi7 hay que recrear mosquitto (ACL) y telegraf, y reconstruir receptor y
  web. Los mensajes llegan cuando las radios estén en `rapa-nui.yaml` (canal 1,
  EasterNetM); hoy el T-Beam de pi7 sigue en el canal del banco.
- Los mensajes viejos que hubiera en `pbx_message` quedan ahí; los nuevos van a
  `message`.

---

## 2026-10-30 — Colores y logo de SASIPA; dos fallas del mapa base
**Time:** 10:15–10:45 (aprox)
**User request:** el usuario agregó `monitor/static/assets/` con los logos
(`sasipa-logo.png`, `sasipa-logo-white.png`, `ssat-logo.png`).

### Actions taken
- `--node` = naranja de SASIPA (`#F37014`, muestreado del logo): nodos del
  mapa y del grafo. Lo planificado: mismo naranja, punteado y casi sin relleno
  (se quitó `--planned`). Curvas de tierra a un arena desaturado, para que el
  naranja resalte.
- Logo de SASIPA (el transparente) en el encabezado del panel de gráficos;
  test de que se sirve desde aquí.
- `fetch.sh`: caja del mapa base de Rapa Nui más ancha (`RAPA_NUI_SEA`, mar
  abierto: el archivo casi no crece) y la del relieve igual que antes. Mapa
  base regenerado.
- Mapa: ajuste a los nodos sin animación. Con la animación, el mapa base pedía
  teselas para los cuadros intermedios y una franja del borde quedaba vacía
  (reproducido en Chrome headless a 911 px; todas las teselas estaban en el
  archivo).
- `map_urls()`: la URL del mapa base y del relieve lleva el hash de
  `maps/SHA256SUMS` (`?v=`). El navegador lee el mapa base por rangos y, la
  primera vez tras regenerarlo, mezcló rangos del archivo viejo: isla vacía
  hasta recargar. Con la versión en la URL, cada archivo es otra dirección.

### Outcomes
- Capturas a 911×512: nodos naranjas sobre curvas arena, logo en el panel,
  sin franja vacía. 261/261 tests.

- Pedido siguiente: que el grafo diga de qué malla es. `gateway/deployment.py`
  lee además `meta.description` y la región, el preset y el slot del bloque
  `radio` (opcionales; con tipo equivocado, error). Todas las páginas reciben
  `mesh` (nombre, descripción, radio): etiqueta con el nombre en la barra
  superior; el grafo titulado "Meshtastic mesh rapa-nui" con la descripción y
  "ANZ · MEDIUM_FAST · slot 45". Sin deployment, el grafo lo dice. GW dentro de
  su círculo (que crece con el nombre); en un grafo chico, la etiqueta de cada
  línea muestra solo el SNR. 265/265 tests.

### Next steps / open questions
- `ssat-logo.png` y `sasipa-logo-white.png` sin uso: preguntar dónde van.
- La descripción de `rapa-nui.yaml` dice "node sites to be defined": ya hay
  sitios planificados. Se cambia en la plataforma y se vuelve a copiar.

---

## 2026-10-29 — Dashboard: LoRa Mesh, paleta Meshtastic, grafo de enlaces
**Time:** 16:40–17:30 (aprox)
**User request:** en su laptop Windows (pantalla reducida) los gráficos no se
ven bien; "LoRa Mesh" en vez de "LoRa Testbed"; paleta tipo Meshtastic; un
grafo de los enlaces sin salto en otra pestaña junto a Map; logo de SASIPA en
los paneles de gráficos y nodos con su color; gráficos solo de los sensores
que existen (sin SHT4X, sin temperatura ni humedad); el uptime no como
gráfico, sino en el popup del nodo. pi7 ya pasó a `sasipa/rapa-nui`.

### Actions taken
- `main.css`: variables de color (fondos neutros oscuros, verde Meshtastic
  `#67EA94` como acento, `--node` para los nodos, `--planned`); `main.css` se
  carga después de `leaflet.css`, así los popups toman esos colores (antes
  salían blancos).
- `base.html`: "LoRa Mesh"; pestaña Graph junto a Map.
- `dashboard.html`: grilla `auto-fill` con tarjetas de 240 px y scroll, en vez
  de meter todos los gráficos en la altura de la ventana; sin gráfico de
  uptime; temperatura y humedad solo si el nodo declara el flujo
  `environment` (V3b: ⇔ SHT4X); encabezado con nombre e ID; SNR en dB.
- `/api/nodes`: último uptime de cada nodo y su hora (`get_nodes_uptime`);
  el mapa lo muestra en el popup como HH:MM:SS, con la hora del reporte.
  Marcadores como círculos de color `--node`.
- `/graph` + `/api/links?hours=`: por nodo, paquetes oídos sin salto (`hop =
  0`) con RSSI y SNR medios, y los que llegaron por relay (`get_links`).
  SVG sin librería nueva: gateway al centro, nodos en círculo; línea solo si
  hubo enlace directo (color por SNR, grosor por cantidad), punteada si solo
  por relay, nodo gris si no se oyó.
- Tests: API de enlaces, uptime, gráficos según sensor, marca, página del
  grafo sin recursos externos, consultas nuevas que fallan con error.

### Outcomes
- Consultas InfluxQL probadas contra un InfluxDB 1.8 local con datos
  sintéticos (ventana, directos y por relay, uptime con su hora).
- Capturas en Chrome headless a 911×512 (1366×768 al 150 %): dos columnas
  legibles con scroll, grafo legible, popup oscuro con el uptime.
- 259/259 tests.

### Next steps / open questions
- Logo de SASIPA: no está en los repos (el `logo16.pdf` de la guía es el de
  CPS-RTC). Con el archivo: logo en los paneles de gráficos y `--node` con su
  color.
- pi7 no responde por la red de la oficina (en modo punto de acceso): el
  despliegue lo hace el usuario.

---

## 2026-10-29 — Punto de acceso en terreno, mapa offline y sitios de SASIPA
**Time:** 13:00–14:00 (aprox)
**User request:** red local en terreno (RaspAP o hotspot propio); guía paso a
paso para activar el punto de acceso y volver a la oficina; mapa offline de San
Joaquín e Isla de Pascua con batimetría. Después: los sitios de SASIPA ya están
en `meshtastic-platform/deployments/sasipa/` (Google Earth, o sea planificados);
editar el deployment de la plataforma (autorizado) y dejar la copia en una
carpeta `sasipa`.

### Actions taken
- pi7 revisada: NetworkManager 1.42.4, país `CL`, llega a la oficina solo por
  WiFi (`preconfigured`, SSID `oficina_v2`; `eth0` sin cable), sin RTC
  (chrony + fake-hwclock), contenedores `restart: unless-stopped`.
- `docs/field-hotspot.md` (enlazado desde el README): perfil `terreno-ap` de
  NetworkManager en modo AP con `ipv4.method shared` (10.42.0.1), prueba en la
  oficina, modo terreno por prioridad de autoconexión, hora de la Pi desde la
  laptop, regreso a la oficina. No se aplicó nada en pi7.
- `tools/bathymetry.py` (+ `tests/test_bathymetry.py`, 7 tests): grilla
  GEBCO_2020 recortada por el ERDDAP de NOAA → curvas de 100–3000 m en GeoJSON
  con `contourpy` (agregado a `tools/requirements.txt`). Rapa Nui: 169 × 217
  celdas, 94 líneas, 145 KiB. Una caja sin mar falla con mensaje.
- `monitor/static/vendor/fetch.sh`: protomaps-leaflet 5.1.0 y las licencias de
  lo que trae empaquetado; el script ahora entiende paquetes con scope
  (`@mapbox/...`). Los archivos que ya estaban no cambiaron (mismos hashes).
- `monitor/static/maps/fetch.sh` (nuevo): extracto `pmtiles` del build
  Protomaps 20261029 para las dos cajas (MultiPolygon, maxzoom 15) +
  batimetría + `SHA256SUMS`.
- `map.html`: mapa base offline (`flavor: dark`, nombres en español), capa de
  curvas con tooltip de profundidad y control para ocultarla; si faltan, lo
  dice en la barra de estado. Ya no se pide nada a openstreetmap.org.
- `tests/test_monitor.py`: la página del mapa lee sus datos de este servidor,
  los sirve por rangos (206) y coinciden con `SHA256SUMS`.
- Plataforma (autorizado): `deployments/rapa-nui.yaml` con `site.planned` para
  N1–N5 y GW desde `deployments/sasipa/sitios_sasipa.json` (lat, lon, alt_m y su
  fuente); N6 toma el punto del GW (el usuario: N6 es el relay hacia la LILYGO
  de las oficinas de SASIPA); cabecera actualizada. `configure.py validate -d rapa-nui` ✓ (solo
  advertencias de lo que falta medir); `test_registry` + `test_hard_rules` OK.
- Plataforma: IDs de N1–N3 (`!0b64122b`, `!7c70da02`, `!32fe0d4e`: los N1–N3
  de San Joaquín) y `hop_limit: 3` en N1–N6, según el usuario. N4–N6: primero
  llegaron con los IDs de N1–N3 (V1 exige únicos); corregidos por el usuario a
  los tres SenseCAP de `office-bench` (`!886217f0`, `!99546767`, `!403192d7`),
  con sus MAC. `validate` ✓.
- Plataforma, a pedido: R1/R2 → D1/D2 con `function: access` (nodos para
  acceder a la malla desde un teléfono o PC; siguen CLIENT_MUTE, posición cada
  900 s); MAC de N1 y N2; se quitó la mención al receptor del estudio de canal
  en N6. `access` se agregó a `FUNCTIONS` en `registry/model.py`. El resto del
  cambio de código en la plataforma (GPS explícito en `provision/plan.py`,
  plantilla, tests) lo bloqueó el clasificador de permisos: queda pendiente.
- Plataforma, hecho por otra mano durante la sesión: `deployments/sasipa/` pasó
  a `deployments/sasipa-info/` (el yaml ya apunta ahí), y `tx_power_dbm` de
  N1–N6 pasó de 22 a 30. Con 30, `validate` falla (V2: el SX1262 llega a 22 dBm
  y se supera el tope EIRP de SUBTEL) y también `test_every_deployment_validates`.
  No se revirtió: lo decide el usuario.
- Dashboard: uptime como tiempo de vida en HH:MM:SS (valor en vivo, eje y
  tooltip), con marcas del eje en pasos redondos (minutos, horas, 3/6/12/24 h).
  Probado en Chrome headless con una serie sintética con un reinicio.
- Mapa, tras verlo en pi7 (abría en la vista del mundo: `office-bench` no tiene
  posiciones): abre en Rapa Nui (`HOME`, `minZoom: 9`); `tools/bathymetry.py` →
  `tools/relief.py`, curvas de elevación (50–500 m) y de profundidad
  (100–2000 m) de GEBCO en una caja de ~10 km alrededor de la isla
  (`relief.geojson`, 49 líneas, 68 KiB); tierra en tonos tierra, mar en azules;
  marcadores planificados en rosa. `fetch.sh` ejecutado con el `pmtiles` que
  instaló el usuario. 253/253 tests.
- pi7: los tres SenseCAP de `office-bench` callados desde el 10-28 ~14:26, con
  74–92 % de batería y el mismo uptime (18703 s): se apagaron juntos.
- Gateway: copia idéntica en `deployments/sasipa/rapa-nui.yaml` (sha
  `b389bb13…`), seleccionable con `MESH_DEPLOYMENT=sasipa/rapa-nui` sin cambiar
  código; documentado en `deployments/README.md` y `.env.example`.
- `gateway/deployment.py`: `Surveyed` → `Position`; `Node.planned` se lee
  aparte de `Node.surveyed`, con las mismas reglas. `/api/nodes`: medido >
  GPS > planificado (`source: "planned"`, `node_id` puede ser null). El mapa
  dibuja lo planificado como círculo ámbar punteado, sin enlace al dashboard
  si no hay `node_id`. Nodos en el mismo punto comparten un marcador cuyo
  popup los lista a todos (N6 y GW), en vez de taparse.
- Tests: posiciones planificadas (fixture), carpeta/nombre, y que cada
  deployment del repo carga.

### Decisions
- Hotspot propio con NetworkManager, no RaspAP: RaspAP no soporta 32 bits con
  escritorio, pide sistema limpio, ocupa el puerto 80 (lighttpd) y suma dhcpcd
  sobre NetworkManager.
- Mapa base vectorial (PMTiles de Protomaps), no teselas raster: los servidores
  de teselas de OSM prohíben la descarga masiva.
- Lo planificado se muestra, pero nunca como medido: el mapa lo usa solo cuando
  no hay ni posición medida ni GPS, y lo dibuja distinto.
- La copia de la plataforma sigue en `deployments/rapa-nui.yaml`: su `-d`,
  `validate --all` y la regla de nombres de `test_hard_rules` solo leen
  `deployments/*.yaml`. Moverla a `sasipa/` exige cambiar ese código.

### Outcomes
- Prueba local con Chrome headless, la página real con una base de datos falsa
  y los sitios candidatos del anexo B.1 como marcadores provisorios (copia en
  el scratchpad, no en el repo): mapa base, curvas y marcadores correctos.
- Con el archivo real: 7 nodos planificados en 6 marcadores; el de las
  oficinas de SASIPA lista N6 y GW (comprobado con Chrome headless).
- 251/253 tests: los 2 que fallan esperan `basemap.pmtiles`.

### Next steps / open questions
- Falta `basemap.pmtiles`: el clasificador de permisos bloqueó descargar y
  ejecutar el binario `pmtiles` (go-pmtiles). El usuario decide cómo seguir.
- MAC de N1–N3 (no están en `san-joaquin.yaml`) y firmware de N1–N6: se leen
  con `configure.py inspect`.
- `tx_power_dbm: 30` en N1–N6: el archivo no valida hasta corregirlo (el
  usuario lo leyó en los nodos del campus: es la configuración, el SX1262 emite
  como máximo 22).
- Elevación en tierra más fina que GEBCO (SRTM 30 m), si el demo lo pide.
- Completar `access` en la plataforma (plan, plantilla, tests) con permiso.

---

## 2026-10-28 — Contraseña del dashboard en pi7
**Time:** 15:40–15:50 (aprox)
**User request:** dónde están las credenciales del dashboard; cambiar la
contraseña generada por una fácil de recordar, elegida por el usuario.

### Actions taken
- pi7: hash nuevo con `caddy hash-password`, escrito entre comillas simples en
  `secrets/proxy.env` (sigue 0600); `docker compose up -d --force-recreate proxy`.
  La receta se probó antes en local (Compose no interpola el hash, Caddy acepta
  la contraseña).

### Decisions
- La contraseña no se escribe en el repo: está en poder del usuario. En pi7 solo
  queda su hash.

### Outcomes
- `http://10.6.5.7/`: sin credenciales 401; usuario `dashboard` con la
  contraseña nueva 200; la generada por `init-credentials.sh` ya no entra (401).

### Next steps / open questions
- Antes de la demo con SASIPA, si la red es compartida, poner una contraseña
  larga (misma receta, `docs/troubleshooting.md`, "The dashboard login").

---

## 2026-10-28 — Banco de la oficina midiendo bien en pi7
**Time:** 09:15–09:25 (aprox)
**User request:** opción (a): base vacía y redespliegue con los cambios
(commits `6239c7f` gateway y `e2e2aee` plataforma, ya publicados).

### Actions taken
- pi7: `git pull --ff-only` (sin cambios locales) → `6239c7f`; deployment sha
  `51242653…`, N1–N3 a 60 s, `STARTUP_SETTLE_SEC = 10`.
- `docker compose down -v` (borra datos de InfluxDB y de Caddy) y
  `up -d --build` (4 min 20 s). Las cuentas de InfluxDB se recrearon desde
  `secrets/`; Telegraf 3 entradas, 0 errores.

### Outcomes
- La ráfaga del arranque (relojes de nodo 125, 185, 245, 365: los SenseCAP se
  reiniciaron al reprovisionarlos) se publicó sin puntuar; el aviso salió una
  vez; ninguna alarma de llegada temprana.
- Tras la ventana, en los tres nodos: un paquete cada 60,0–60,1 s,
  `missed_est 0`, `early_count 0`, `cadence_violated 0`, PDR 1.0. Datos en la
  base nueva, leídos por el dashboard.

### Next steps / open questions
- En InfluxDB, dos paquetes del mismo nodo en el mismo segundo (solo pasa en la
  ráfaga de arranque) siguen pisándose: `received_at` tiene resolución de 1 s.

---

## 2026-10-27 — Cadencia de 60 s y ventana de arranque
**Time:** 17:10–17:25 (aprox)
**User request:** la cadencia real de los SenseCAP es 60 s (el usuario la
cambió); llevarla al `.yaml`. Aprobada la ventana de arranque sin puntuar.

### Actions taken
- `office-bench.yaml` (plataforma, la fuente): N1–N3 `intervals: {device: 60}`.
  `validate` OK; copia idéntica en el gateway (sha `51242653…`).
- `gateway/receiver.py`: `settle_sec` (0 por defecto, así los tests y la
  equivalencia con el monorepo no cambian); `main.py` pasa 10 s. Lo recibido
  en esa ventana se publica sin campos PDR y sin puntuar; aviso una sola vez;
  `report()` cuenta `pdr_unscored_at_startup`. La detección de reinicios sigue
  activa.
- `tests/test_receiver.py::TestStartupSettling` (3); mutación (sin ventana) →
  2 fallan. **241 tests en verde.** `docs/design.md` §4.

### Next steps / open questions
- Usuario: commit y push (gateway y plataforma). Luego en pi7: `git pull` y
  `docker compose up -d --build`. Lo que InfluxDB guardó con la cadencia de
  120 s tiene PDR inválido: empezar con la base vacía (`down -v`) o anotar desde
  cuándo vale.

---

## 2026-10-27 — El gateway corriendo en pi7 con el banco de la oficina
**Time:** 16:55–17:10 (aprox)
**User request:** el usuario clonó el repo en pi7 (`~/Desktop/meshtastic-gateway`,
commit `f25ef2f`), creó `.env`, registró `GW` en `office-bench.yaml` (tres
copias idénticas, sha `4e9076…`), generó las credenciales y conectó el T-Beam.

### Actions taken
- `.env` de pi7: `MESH_DEPLOYMENT=office-bench`, `MQTT_TOPIC_PREFIX=office-bench`,
  `INFLUXDB_IMAGE=influxdb:1.8`, `GATEWAY_SERIAL_PORT=/dev/serial/by-id/usb-1a86_USB_Single_Serial_5896111599-if00`.
- Radio leída (solo lectura) antes de usarla: `!6c74104c`, 2.7.26,
  `CLIENT_MUTE`, ANZ MEDIUM_FAST slot 45, 2 dBm, canal `miniT`: provisionada.
- Credenciales: completas (secrets 700/600, pwfile 600 uid 1883, sin restos).
- `docker compose up -d --build` (2 min 46 s): seis servicios arriba; el
  receiver arranca sin warnings de inicio (sha correcto, N1–N3 y GW conocidos,
  radio GW en CLIENT_MUTE), Telegraf con 3 entradas, datos en InfluxDB.

### Outcomes — hallazgos de la primera corrida real
- **Los SenseCAP transmiten telemetría de dispositivo cada 60 s, no 120 s**
  (reloj del nodo: N1 16119→16179→16239; N3 14615→14675→14735). Con 120 s
  declarados, el estimador ve cada paquete a media cadencia y lo cuenta como
  temprano: `cadence_violated=1`, PDR inválido. El warning de G10 lo dijo al
  arrancar. La plataforma traduce `device: 120` a
  `telemetry.device_update_interval = 120`; queda por ver qué tienen
  configurado los nodos (inspector de la plataforma, por USB).
- **Ráfaga al conectar**: al abrir el puerto, el T-Beam se reinicia y luego
  entrega de golpe paquetes retenidos (dos por nodo, 0,1 s entre sí). El
  estimador los toma como llegadas tempranas aunque fueron emitidos 60 s
  aparte; además, por el reinicio se pierde un paquete por nodo.
- Esos dos paquetes de la ráfaga comparten segundo (`received_at`) y tags, así
  que en InfluxDB el segundo pisa al primero.

### Next steps / open questions
- Usuario: `python configure.py inspect -d office-bench --node N1 --port ...`
  en un SenseCAP: ¿qué `device_update_interval` tiene? Si 60 s es lo deseado,
  declarar `device: 60` (y sincronizar las tres copias); si no, reprovisionar.
- Proponer al usuario: no puntuar en el PDR los paquetes que llegan en los
  primeros segundos tras conectar (se publican igual).

---

## 2026-10-27 — pi7: Docker en 32 bits y el deployment `office-bench`
**Time:** 15:55–16:45 (aprox)
**User request:** usar pi7 como host del gateway (radio aún sin flashear; será
otro T-Beam). Docker para el sistema de 32 bits. Crear un deployment nuevo con
los tres SenseCAP del banco de su oficina (node_id, MAC, firmware 2.7.26), para
configurar desde la plataforma el T-Beam como gateway y probar el banco.

### Actions taken
- pi7 (`ssh pi7`, 10.6.5.7, `rpi7`): Raspberry Pi 4 con **Raspberry Pi OS de 32
  bits** (`armhf`, kernel de 64). Reloj sincronizado, 45 GB libres, 7,6 GB RAM,
  puerto 80 libre, internet. Contiene `~/Desktop/vertex-testbed` con 5,1 GB de
  `data/` **nunca commiteados** (solo existen ahí): no reinstalar sin respaldo.
- La guía de Ubuntu no aplica (no es Ubuntu). Docker **28.5.2** + Compose
  instalados desde el repositorio `raspbian` oficial de Docker (su guía para
  32 bits; la 28 es la última mayor para 32 bits); `rpi7` en el grupo `docker`;
  `hello-world` corre como `arm32v7`.
- Imágenes en 32 bits: `influxdb:1.11-alpine` y `telegraf:1.32-alpine` no
  existen para `arm/v7`. Compose: `telegraf:1.32` (Debian, multi-arquitectura)
  para todos; InfluxDB configurable con `INFLUXDB_IMAGE` (por defecto 1.11;
  `influxdb:1.8` en pi7: mismas variables de cuentas, verificado en su script).
  Mosquitto corre como `arm/v6`. Las cuatro descargadas en pi7.
- Primera compilación en pi7: fallaron `greenlet` y `msgpack` (sin wheel para
  32 bits, y la imagen no tiene compilador); `dbus-fast` también compila. Los
  dos Dockerfiles ahora construyen los wheels en una etapa con compilador y la
  imagen final los instala sin él (verificado en amd64: sin `gcc`, imports
  correctos, el receiver como `gateway` en `dialout`).
- `meshtastic-platform/deployments/office-bench.yaml` (pedido explícito del
  usuario): `kind: bench`, bloque de radio idéntico a `mini.yaml` (canal
  `miniT`, `MINI_PSK`, slot 45: N1–N3 ya fueron provisionados con él), N1–N3
  `deployed` con node_id/MAC/firmware de su tabla, `GW` (T-Beam,
  `function: gateway`, `CLIENT_MUTE`) en `planned`; potencia mínima del chip
  (-9 dBm SenseCAP, 2 dBm T-Beam), como exige el validador para un banco.
  `validate` OK (avisos esperados: GW sin registrar; MCU mixtas);
  `validate --all` OK; 204 tests de la plataforma en verde. Copia idéntica en
  `deployments/` del gateway (mismo sha256); el lector del gateway conoce N1–N3.
- `docs/troubleshooting.md`: "A 32-bit Raspberry Pi". Memoria: `pi7-gateway-host`.
- **238 tests en verde.**
- Segunda compilación en pi7 (copia del árbol en `/tmp/gwbuild`): ambas
  imágenes OK en 3 min 28 s (compila `dbus-fast`, `greenlet`, `msgpack`).
- **Prueba en vivo en pi7** (credenciales de prueba, `influxdb:1.8`): los cinco
  servicios arriba; Telegraf conectado en sus 3 entradas; InfluxDB sin
  credenciales → 401. Desde la imagen del receiver se publicó telemetría de
  N1–N3; desde la laptop, por la red: dashboard sin login 401, con login 200,
  voltaje de N1 por `/api/recent` a través del proxy; 1883, 5000 y 8086
  cerrados desde la red. Desmontado (contenedores y volúmenes); credenciales de
  prueba borradas; imágenes conservadas como caché.

### Decisions
- `kind: bench` y no `field`: con `field`, un nodo `deployed` exige posición
  medida en terreno, y la plataforma prohíbe coordenadas de escritorio.
- N1–N3 siguen con los 22 dBm de `mini` hasta reprovisionarlos con este archivo
  (mismo canal, solo cambia la potencia): hasta entonces el inspector de la
  plataforma marcará su potencia.

### Next steps / open questions
- Usuario: flashear el T-Beam (2.7.26, borrado completo), `inspect` → registrar
  GW en `office-bench.yaml` → `validate` → `provision --node GW`; recopiar el
  archivo al gateway; conectarlo a pi7.

---

## 2026-10-27 — README, `docs/design.md` y preparación del primer commit
**Time:** 10:25–10:40 (aprox)
**User request:** incluir el diagrama nuevo en un `.md` (un README breve); ¿está
terminado lo de las directivas y el refactor? Quiere borrar
`GATEWAY-DIRECTIVES.md` y `REFACTOR-PLATFORM-GATEWAY.md`, hacer el primer
commit y el push.

### Actions taken
- `README.md`: qué es, el diagrama (`docs/diagrams/port-architecture.png`),
  puesta en marcha en 4 pasos, mapa del repositorio, desarrollo y tests, índice
  de la documentación.
- `docs/design.md`: lo durable de GATEWAY-DIRECTIVES, sin el plan de trabajo —
  frontera con la plataforma y la decisión de no depender de su código, el
  contrato publicado (campos, reglas, diferencias deliberadas con el monorepo,
  tópicos, mediciones, cuentas y puertos), invariantes del estimador de PDR,
  forma del receiver, invariantes G1–G13 (misma numeración que citan el código
  y troubleshooting) y lo decidido fuera o diferido.
- Seis referencias a GATEWAY-DIRECTIVES en código y tests →
  `docs/design.md`. Fuera de los dos archivos solo las menciona esta bitácora
  (historia). Enlaces relativos del README y de `design.md` verificados.
- Auditoría de `git add -A --dry-run`: sin `.env`, `secrets/`, `pwfile`,
  `.venv` ni caches. Quitadas 12 imágenes copiadas del monorepo que nada usa
  (1,2 MB; solo el favicon se usa): no entran para siempre en el historial.
- **238 tests en verde.**

### Decisions
- Sí está terminado para este alcance: pasos 1–6, 8 y 9 hechos, 7 descartado.
  Diferido, no bloqueante: dónde va el PBX; mapas y batimetría offline;
  migrar eventlet; imágenes base por digest.

### Next steps / open questions
- Usuario: borrar los dos documentos, primer commit y push a `origin/main`.
- Luego, en la plataforma: agregar el gateway como submódulo de referencia y
  corregir su CLAUDE.md y su memoria, que aún dicen que el gateway reutiliza su
  código.

---

## 2026-10-27 — Diagrama TikZ de la arquitectura de puertos
**Time:** 10:15–10:30 (aprox)
**User request:** (desde la sesión de `meshtastic-platform`) dibujar en TeX la
arquitectura de puertos de la opción B, a partir de su resumen y de esta
implementación. Es el diagrama que la entrada "Opción B" dejó a otro agente.

### Actions taken
- `docs/diagrams/port-architecture.tex` (TikZ standalone) → `.png` (300 dpi) y
  `.pdf`: zonas (red de terreno, host, red de Compose, loopback 127.0.0.1),
  los seis contenedores con su puerto interno y cómo se publica, los flujos
  1–8 con protocolo y cuenta, una tabla con lo que puede cada cuenta, y lo
  ausente a propósito (TLS, listener websocket).
- `docs/diagrams/palette.tex` y `build.sh` copiados de `meshtastic-platform`
  (mismo aspecto que sus diagramas). Compilar: `docs/diagrams/build.sh`.

### Decisions
- Vive aquí y no en la plataforma: la regla 2 de ese repositorio prohíbe mencionar
  broker, base de datos o contenedores.
- Datos tomados de `docker-compose.yaml`, `proxy/Caddyfile`,
  `mqtt/aclfile.template`, `telegraf.conf` y los Dockerfiles. Las flechas MQTT
  siguen al mensaje; las HTTP, al request (como en el resumen del usuario).
- No nombra archivos de credenciales: sigue siendo válido con las
  credenciales por servicio de la entrada siguiente.

### Next steps / open questions
- Si cambia un puerto, una cuenta o un servicio, actualizar el diagrama.

---

## 2026-10-27 — Credenciales por servicio
**Time:** 10:15–10:35 (aprox)
**User request:** "yes" al diseño de archivos de credenciales por servicio.

### Actions taken
- `mqtt/init-credentials.sh` reescrito: genera todas las credenciales en un
  directorio temporal (incluido `mosquitto_passwd`, ahora como el usuario del
  host para que lo temporal sea borrable) y recién al final mueve
  `secrets/` (700; `influxdb`, `telegraf`, `gateway`, `web`, `proxy`.env, 600)
  y `mqtt/pwfile` (1883, 600). Se niega si existe cualquiera de los dos. Solo
  imprime la contraseña del dashboard. Nada que copiar a mano.
- Compose: un `env_file` por servicio (`mosquitto`, ninguno);
  `INFLUXDB_DB` pasa a `.env` (obligatorio, `:?`) por un ancla.
  `configuration.env.example` eliminado; `.gitignore` ignora `secrets/` y
  `.credentials.*`.
- Referencias actualizadas: pista G5 del gateway y del dashboard, `plot_history`
  (`set -a; . ./.env; . ./secrets/web.env; set +a`), comentarios, `.env.example`,
  troubleshooting (G5 reescrita; el ejemplo de `mosquitto_sub` usa la cuenta de
  Telegraf porque `monitor` ya no lee todo; "expect 3" entradas de Telegraf;
  nueva sección "Rotating the credentials" con `SET PASSWORD` y la contraseña
  admin vieja), directivas (G5, G9, §1.5).
- `tests/test_infrastructure.py::TestCredentialsPerService` (5): cada archivo
  tiene exactamente las claves de su servicio; cada servicio su archivo; solo
  `influxdb` conoce la contraseña admin; toda variable de `telegraf.conf` y del
  Caddyfile, y toda credencial que leen el receiver y el dashboard, existe en su
  archivo. **238 tests en verde.**
- **Prueba en vivo** (`gwtest`, desmontado): con Docker inaccesible el script
  falla sin dejar nada; corrida normal con permisos correctos; segunda corrida
  rechazada. Stack arriba: el entorno de cada contenedor tiene solo sus
  credenciales (el receiver, solo su cuenta MQTT); el receiver publica, Telegraf
  escribe sin errores, el dashboard responde por el proxy, `plot_history`
  funciona con `secrets/web.env`.

### Next steps / open questions
- Más adelante: mapas y batimetría offline (San Joaquín, Isla de Pascua) para
  el demo de SASIPA.

---

## 2026-10-27 — Opción B: un proxy con login como única puerta
**Time:** 09:55–10:15 (aprox)
**User request:** opción B (localhost + proxy con login); el diagrama `.tex`
de la arquitectura lo hará otro agente. Pregunta: cómo escribiría
`init-credentials.sh` un archivo por servicio (sin aprobar aún).

### Actions taken
- `proxy/Caddyfile` (Caddy 2.10): `basic_auth` con `DASHBOARD_USER` y
  `DASHBOARD_PASSWORD_HASH` (bcrypt), `reverse_proxy web:5000`, sin HTTPS
  automático (offline no hay certificado de confianza; protege el WPA2 de la
  WiFi de terreno) y sin API de administración.
- Compose: servicio `proxy` en `${DASHBOARD_PORT:-80}`, la única puerta a la
  red; `web` → `127.0.0.1:5000`, `influxdb` → `127.0.0.1:8086` (MQTT ya estaba
  en localhost). Volumen `caddy_data`.
- Feed en vivo: por defecto, mismo origen (lo que el navegador haya escrito
  para llegar al proxy: `gateway.local`, una IP); `MONITOR_ALLOWED_ORIGINS`
  queda opcional.
- `init-credentials.sh`: genera la contraseña del dashboard, guarda solo su
  hash bcrypt (con el `caddy` del compose) y muestra la contraseña una vez.
- **Trampa encontrada**: Compose interpola los `$` dentro de los env files; un
  hash bcrypt sin comillas queda truncado (solo un warning) y todo login falla.
  El hash va entre comillas simples; test que lo fija.
- Tests (`TestHardening`): solo el proxy abierto a la red; el Caddyfile pide
  login; hash entre comillas; el script usa la misma imagen de Caddy. **233 en
  verde.**
- **Prueba en vivo** (`gwtest`, desmontado): en la red solo `:80`; el resto
  en `127.0.0.1`. Sin login / login errado → 401; correcto → 200 (mapa, API),
  por `localhost` y por la IP de la LAN. Socket.IO a través del proxy, como un
  navegador (credenciales en cada request): conecta desde ambos orígenes sin
  configurar nada; otro sitio → 400; sin login → 401; llega solo telemetría.
  (El cliente Python de Socket.IO manda las credenciales solo en el primer
  request y fallaba con 401: artefacto del cliente, no de la arquitectura.)
  Caddy sin usuario o con hash inválido: se niega a arrancar.
- `docs/troubleshooting.md`: "The dashboard login"; "No live updates"
  reescrita. GATEWAY-DIRECTIVES: §1.5, §3 (`proxy`, seis servicios), G13.

### Next steps / open questions
- Usuario: aprobar los archivos de credenciales por servicio (diseño propuesto
  en la respuesta: `secrets/<servicio>.env` escritos por el script, sin copiar
  y pegar).

---

## 2026-10-27 — Decisiones de seguridad y `plot_history`
**Time:** 09:20–09:35 (aprox)
**User request:** respuestas a los abiertos del paso 8 — (1) explicar la
arquitectura de puertos (localhost / localhost + proxy) con diagramas; (2)
qué servicio usa qué credencial; (3) ok al número sintético; (4) sí a usar el
dashboard en terreno sin internet (más adelante: mapas y batimetría de San
Joaquín e Isla de Pascua, demo offline para SASIPA); (5) qué es mejor para el
receiver como root; (6) explicar los menores. `plot_history` si produce series
de tiempo estilo IEEE (sí: ancho de doble columna IEEE, estilo paper).

### Actions taken
- (3) Número real reemplazado por `123456789` (cable `07 5B CD 15`; leído en
  little-endian, `365779719`) en fixtures, tests, directivas y bitácora. Cero
  apariciones del real.
- (4) `monitor/static/vendor/`: Leaflet 1.9.4, Chart.js 4.6.1 (lo que hoy
  resolvía `@4`), adapter date-fns 3.0.0, socket.io-client 4.4.1, con licencias.
  `fetch.sh` baja cada archivo de jsDelivr y unpkg, exige que sean idénticos y
  escribe `SHA256SUMS`. `base.html` sin CDN. Tests: ninguna página carga
  scripts/estilos externos; cada archivo coincide con su hash. Solo quedan
  externos los tiles de OpenStreetMap (la tarea de mapas offline).
- (5) Receiver sin root: usuario `gateway` en el grupo `dialout`. Verificado con
  el `/dev/ttyS0` del host (`root:dialout`, gid 20): ese usuario lo abre; uno
  fuera de `dialout`, `Permission denied`. Test en `TestHardening`.
- `tools/plot_history.py` + `tools/plotstyle.py` portados:
  `python -m tools.plot_history` (sin `sys.path`), cuenta de solo lectura,
  roles y colores desde el deployment (el monorepo tenía la lista de nodos y
  sitios en el código), `--format png|pdf|svg` (PDF con fuentes Type 42),
  ceros conservados por defecto (`--drop-zeros` solo para datos del monorepo:
  ahora un SNR de 0.0 dB es real), labels escapados en InfluxQL, campos
  validados, error explícito con credenciales rechazadas.
- Prueba en vivo: 2 h simuladas por el receiver real con una caída de 30 min →
  figuras PNG/PDF desde la base con la cuenta de lectura. La figura mostró un
  error heredado: la línea cruzaba la caída cuando `device` y `environment`
  comparten segundo (mediana de intervalos = 0 desactivaba el corte) →
  corregido (solo intervalos positivos) con test; regenerada, corta bien.
- `tests/test_plot_history.py` (13). **229 tests en verde.**
- La limpieza final del scratchpad fue bloqueada por el chequeo de seguridad
  (un `rm` dentro de `sh -c`); quedaron ahí la copia del stack de prueba, las
  figuras y los arneses de equivalencia.

### Next steps / open questions
- Usuario: elegir entre puertos solo-localhost (túnel SSH) y localhost + proxy
  con login; aprobar archivos de credenciales por servicio.
- Más adelante: mapas offline (tiles) y batimetría de San Joaquín e Isla de
  Pascua para el demo sin internet.

---

## 2026-10-27 — Paso 8: revisión de seguridad
**Time:** 09:10–09:20 (aprox)
**User request:** "sí" al paso 8.

### Actions taken
- La skill `/security-review` no corre aquí (necesita commits y `origin/HEAD`);
  revisión a mano de todo el repositorio.
- Barrido de secretos (G9): nada en lo que se commitearía; `.env`,
  `configuration.env`, `mqtt/pwfile` ignorados; imágenes sin secretos (allowlist).
- Corregido (y verificado en vivo, proyecto `gwtest`, ya desmontado):
  - **InfluxDB sin autenticación** en `0.0.0.0:8086` → `INFLUXDB_HTTP_AUTH_ENABLED`
    + cuentas de mínimo privilegio: Telegraf escribe con `INFLUXDB_WRITE_USER`
    (`skip_database_creation`), el dashboard lee con `INFLUXDB_READ_USER`; el
    admin solo para mantenimiento. Sin credenciales: 401; la cuenta de lectura
    no puede `DROP`.
  - **El feed en vivo reenviaba los mensajes** (números de teléfono) a cualquier
    navegador, sin que el frontend los usara → el dashboard se suscribe solo a
    `position`/`device`/`environment`, y la cuenta `monitor` del ACL solo puede
    leer esos (verificado: `mosquitto_sub` como `monitor` sobre `+/message`
    no recibe nada).
  - **MQTT publicado en todas las interfaces sin TLS**, sin publicadores remotos
    desde que se quitaron los collectors → `127.0.0.1:1883`. Listener websocket
    (9001/9002) sin uso → quitado.
  - **Logs sin límite** con el texto de los mensajes → `json-file` 10 MB × 3
    en todos los servicios.
  - **El dashboard corría como root** → usuario `monitor` (uid 999).
  - `init-credentials.sh` genera también las contraseñas de InfluxDB (no quedan
    `change_me`).
- De paso, falla funcional heredada: los gráficos de RSSI/SNR/saltos no se
  actualizaban en vivo (la clave `rx_metrics` no corresponde a ningún tópico).
- `tests/test_infrastructure.py::TestHardening` (6) fija cada corrección.
  **213 tests en verde.**
- GATEWAY-DIRECTIVES: §1.5, §3, nuevos G11 (auth InfluxDB) y G12 (feed solo
  telemetría), §6 paso 8.

### Abierto, para decisión del usuario
1. **8086 y 5000 siguen en todas las interfaces.** InfluxDB ahora pide
   credenciales; el dashboard no tiene autenticación (cualquiera en la red ve
   posiciones y telemetría). Propuesta: 8086 → `127.0.0.1` (túnel SSH para
   herramientas remotas); 5000 → `127.0.0.1` detrás de un proxy con auth, o
   aceptarlo si la red es de confianza.
2. **Todos los contenedores reciben todos los secretos** (`env_file:
   configuration.env` compartido): el receiver, que procesa tráfico de radio no
   confiable, tiene la contraseña admin de InfluxDB. Propuesta: un archivo de
   entorno por servicio.
3. **Número de teléfono real** (el del handset de la captura del orden de
   bytes) en `tests/fixtures/packets.py`, `golden.py`,
   `test_payload_contract.py`, GATEWAY-DIRECTIVES y esta bitácora. Reemplazar
   por uno sintético antes de publicar (el test de orden de bytes necesita
   recalcular los bytes del cable).
4. **Librerías del frontend desde CDN sin SRI**, dos con versión mayor flotante
   (`chart.js@4`, adapter `@3`). Propuesta: copiarlas a `monitor/static/`
   (además funciona sin internet en terreno).
5. **El receiver corre como root** (necesita el puerto serie). Usuario no root
   con grupo `dialout`; requiere probarlo con hardware.
6. Menores: imágenes base por tag, no por digest; eventlet deprecado;
   `init-credentials.sh` pasa contraseñas como argumentos de `docker run`
   (visibles en `ps` un instante); `FLASK_DEBUG`.
- Pendiente detectado: `tools/plot_history.py` figura en §3 pero ningún paso
  de §6 lo porta.

---

## 2026-10-27 — Sin collectors; el texto de los mensajes PBX en la terminal
**Time:** 08:55–09:10 (aprox)
**User request:** los collectors no van en esta implementación. Opción A
(quitar todo lo que solo existía para ellos), y loguear en la terminal el texto
de los mensajes que llegan por el PBX.

### Actions taken
- Quitado: el kind `pbx` de `publish.KINDS`; la entrada de Telegraf hacia
  `pbx_health`; las cuentas `p1`/`p2` (ACL, `init-credentials.sh`,
  `configuration.env.example`); la sección "collector ports are crossed" de
  troubleshooting; comentarios que los suponían (`mosquitto.conf`, ACL).
  `pbx_message` se queda: lo produce el receiver.
- GATEWAY-DIRECTIVES: §1.3 (sin `pbx`), §1.4 (tres mediciones), §1.5 (tres
  cuentas; solo escribe el gateway), §3 (sin fila de collectors), §3.2 reducida
  a la decisión y lo que se pierde (no se puede separar pérdida BLE / UART /
  aire en los mensajes), §3.1 (log del texto), §5 ("Until it is decided"
  ajustado; la tabla de lecturas queda como registro), §6 paso 7 descartado.
- `gateway/payload.py`: `pbx_frame(decoded)`, compartida por
  `to_message_payload()` y el receiver.
- `gateway/receiver.py`: una línea `[MSG]` por mensaje deduplicado — origen,
  destino o `broadcast`, nodo, canal, saltos, RSSI, SNR y el texto. Caracteres
  de control escapados (un mensaje no puede mover el cursor, colorear el log ni
  falsificar otra línea); lo que no es UTF-8, en hex; las tramas malformadas
  también. El texto sigue sin publicarse por MQTT salvo `capture_content`.
- `tests/test_receiver.py`: `TestMessageLog` (7). **207 tests en verde.**

### Decisions
- Log siempre activo, sin variable de entorno: es lo pedido.
- Se loguea antes de publicar, para que el texto aparezca aunque falle la
  publicación.

### Outcomes
- Ejemplo: `[MSG] 123456789 -> broadcast via node-1 (TEXT_MESSAGE_APP, ch 0,
  hop 1, rssi -95, snr 3.5): "reunion a las 18:00"`.

### Next steps / open questions
- Privacidad: `docker compose logs` conserva el texto en el host (driver
  json-file, sin rotación configurada). Decidir en el paso 8 si se rota o se
  limita.
- Paso 8: revisión de seguridad.

---

## 2026-10-26 — Paso 6: el dashboard (`monitor/`)
**Time:** 16:45–17:00 (aprox)
**User request:** "sí" al paso 6.

### Actions taken
- `gateway/deployment.py` lee `site.surveyed` con las reglas de la plataforma
  (bloque todo nulo = sin medir; a medias = error; `lat`/`lon` en rango y ≠ 0;
  `site.planned` nunca se lee). Fixture con N1 medido y P1 sin medir; 4 tests.
- `gateway/publish.py`: `describe_refusal()` pública, para que el dashboard
  nombre la causa G5 igual que el receiver.
- `monitor/` como paquete (`python -m monitor`, sin trucos de path):
  `param.py` (tópico `<prefijo>/+/+` y `CLIENT_ID` desde `MQTT_TOPIC_PREFIX`;
  base desde `INFLUXDB_DB`, la de Telegraf; `MONITOR_ALLOWED_ORIGINS`), `utils.py`
  (InfluxDB y suscriptor MQTT), `app.py` (`create_app`), `__main__.py`
  (eventlet), `Dockerfile` (contexto raíz: copia `gateway/` y `monitor/`),
  `requirements.txt` (pins del monorepo + pyyaml). Plantillas y estáticos
  copiados.
- Fallas silenciosas del monorepo corregidas:
  - consulta fallida → `[]` con 200 (el mapa decía "no nodes"): ahora 503 con
    el motivo, y `map.html` / `dashboard.html` lo muestran;
  - si InfluxDB no respondía al arrancar, el cliente quedaba en `None` para
    siempre: ahora cada consulta reintenta (verificado en vivo: el dashboard
    arrancó antes que la base y se recuperó);
  - CORS fijo en `http://localhost:5000`: abierto desde otra máquina, sin
    actualizaciones en vivo y sin aviso → configurable;
  - vista inicial fija en San Joaquín y sin reencuadre con un solo nodo →
    vista mundial y encuadre a los nodos; Leaflet sin versión → `@1.9.4`.
- Compose: servicio `web` (prefijo `:?`, `MESH_DEPLOYMENT` `:?`, `deployments/`
  `:ro`). `.dockerignore` permite `monitor/`. Tests de infraestructura
  extendidos a `web` y a las plantillas (sin prefijo literal).
- `tests/test_monitor.py` (15). **200 tests en verde.**
- **Prueba en vivo** (proyecto `gwtest`): cliente Socket.IO desde el origen
  permitido recibe los 4 mensajes del receiver bajo `gwtest/...`; otro origen,
  rechazado (400); `/api/nodes` con la posición medida y el GPS al lado;
  `/api/recent` con historial; páginas 200; InfluxDB detenido → 503 con el
  motivo, y al volver → 200. Todo desmontado.
- `docs/troubleshooting.md`: "The dashboard cannot query InfluxDB" y "No live
  updates in the dashboard". GATEWAY-DIRECTIVES §1.3, §3, §6.

### Decisions
- El dashboard importa el paquete `gateway` (regla del prefijo, lector de
  deployments) en vez de duplicarlos.
- `MESH_DEPLOYMENT` opcional fuera de compose (sin él, solo GPS, con WARNING al
  arrancar); obligatorio en compose, como para el receiver.

### Next steps / open questions
- Paso 7: collectors (`node_logd`, `pbx_logd`) → `gateway/collectors/`.
- eventlet está deprecado (aviso al importarlo); funciona, pero conviene migrar
  a otro modo de Flask-SocketIO más adelante.
- Paso 8: además de InfluxDB sin auth, las librerías del frontend vienen de CDN
  sin SRI.

---

## 2026-10-26 — Paso 5: broker, Telegraf, InfluxDB y compose
**Time:** 16:20–16:45 (aprox)
**User request:** "sí" al paso 5; la prueba con radio real no es necesaria
(ya se probó en el monorepo) → paso 4 marcado hecho.

### Actions taken
- `gateway/publish.py`: el prefijo se restringe a `[A-Za-z0-9._-]+` porque se
  sustituye con `sed` en el ACL y en `telegraf.conf` (`&`, `|` lo romperían en
  silencio). Test nuevo.
- `telegraf/etc/telegraf.conf`: el del monorepo con `${MQTT_TOPIC_PREFIX}` en
  los tópicos y `${INFLUXDB_DB}` como base (una sola fuente).
- `mqtt/`: `mosquitto.conf`; `aclfile.template` con `{prefix}`; `entrypoint.sh`
  la renderiza en cada arranque del broker desde la misma variable (no un
  archivo generado una vez que pueda quedar viejo) y valida el prefijo con la
  misma regla; `init-credentials.sh` portado (mensajes con nombres de servicio).
- `docker-compose.yaml` (4 servicios; `web` en el paso 6): `${VAR:?}` para
  prefijo, deployment y puerto serie; `mqtt/` montado `:ro` (el entrypoint de
  la imagen hacía `chown -R` del directorio del host a uid 1883 en el
  monorepo); `deployments/` montado `:ro`; sin `container_name` fijo.
- `Dockerfile` del receiver; `.dockerignore` como lista de permitidos
  (`requirements.txt`, `gateway/`, `main.py`): ni `.venv` ni secretos (G9).
- `configuration.env.example`; `.gitignore` + `data/`, `log/`.
- `tests/test_infrastructure.py` (10): cada kind de `publish.KINDS` consumido
  exactamente una vez hacia su medición; tags y time key por la tabla §1.4;
  cuentas de `init-credentials.sh` = usuarios del ACL; reglas del ACL; ningún
  prefijo literal; compose exige el prefijo en los tres servicios y los
  obligatorios del receiver; montajes `:ro`. **181 tests en verde.**
- **Prueba en vivo** (copia del repo en el scratchpad, proyecto `gwtest`,
  credenciales de `init-credentials.sh`):
  - Telegraf conectado en sus 4 entradas con su cuenta; ACL renderizado para
    `gwtest` (0600, mosquitto); `mqtt/` del host sin cambio de dueño.
  - El `Receiver` real, con paquetes de fixtures, contra el broker real: las
    **4 mediciones pobladas** con sus tags; `dst_id` vacío en broadcast;
    `malformed=1`; filas `pdr` del sweep; `pbx_health` de `p1`.
  - `p1` publicando en `gwtest/p2/pbx`: descartado por el ACL **sin log** en
    el broker (anotado en troubleshooting).
  - Contraseña equivocada: `Not authorized — mqtt/pwfile and configuration.env
    must be generated together...` (G5).
  - Imagen del receiver: solo `gateway/`, `main.py`, `requirements.txt`. Sin
    configuración: exit 2 con el motivo. Con todo configurado: carga el
    deployment montado, imprime el sha256, conecta al broker; `/dev/null` como
    radio → traceback y exit 1. Compose sin prefijo: se niega a arrancar.
  - Todo desmontado (contenedores, volumen, red, imagen) y el scratchpad limpio.
- `docs/troubleshooting.md`: G5 primero; nuevas entradas "Published, never
  stored" (G4, ACL silencioso), "The gateway restarts in a loop" (exit 2/1),
  "Drift warnings" (G10); lo del lado de los nodos remite a la plataforma.
- GATEWAY-DIRECTIVES §1.3, §1.5, §3, §6 (pasos 4 y 5 hechos).

### Decisions
- ACL renderizado al arrancar el contenedor, no generado una vez.
- Sin `container_name` fijo: troubleshooting usa `docker compose logs <servicio>`.

### Next steps / open questions
- Paso 6: `monitor/` (rutas `/`, `/map`, `/dashboard`, `/api/...`), con
  `SUBSCRIBE_TOPIC` derivado de `MQTT_TOPIC_PREFIX`; el `.dockerignore` deberá
  permitir lo que su imagen copie.
- Paso 8 (seguridad): InfluxDB publica 8086 en el host sin
  `INFLUXDB_HTTP_AUTH_ENABLED` (como en el monorepo): lectura/escritura sin
  credenciales desde la red.

---

## 2026-10-26 — Paso 4: el receiver
**Time:** 16:05–16:20 (aprox)
**User request:** "sí" a seguir con el paso 4.

### Actions taken
- `requirements.txt`: `meshtastic==2.7.8`, `Pypubsub==4.0.7`, `pyyaml==6.0.3`
  (las versiones de la plataforma y del monorepo).
- `gateway/deployment.py`: lector propio. Semántica verificada en el código de
  la plataforma: nombre publicado = `label` o `ref`; nodos conocidos = los que
  tienen `node_id`; cadencias divididas por `cadence_scale`; un flujo que no se
  emite está ausente (null/0 es error); `node_id` = `!` + 8 hex. Estricto en lo
  que lee, ignora el resto; sha256 de los bytes; rechaza duplicados (ref,
  nombre publicado, `node_id`) y `meta.deployment` distinto del archivo;
  informa todos los problemas a la vez.
- `gateway/config.py`: obligatorios `MESH_DEPLOYMENT`, `MQTT_TOPIC_PREFIX`,
  `GATEWAY_SERIAL_PORT`; el resto con default. `CLIENT_ID` por defecto
  `<prefijo>-gateway` (dos clientes con el mismo id se expulsan mutuamente del
  broker). `PDR_WINDOW_SEC` con override por flujo; `PDR_SWEEP_INTERVAL_SEC`.
- `gateway/receiver.py`: el cableado de `MeshReceiver`, con relojes inyectados.
  Descarta y cuenta por motivo: propios, encrypted/empty, remitente
  desconocido, duplicados, no publicables. Reboot antes de puntuar; hold de
  `device_ts` por `(node_id, flujo)`; warnings G10 una vez cada uno (remitente
  desconocido, flujo sin cadencia, `cadence_violated`); `report()`.
  `on_receive` nunca lanza: cuenta el error y loguea el traceback.
- `gateway/startup.py`: warnings de arranque — la radio no está en el deployment
  o no es `gateway`; rol distinto de `CLIENT_MUTE` (G6); sweep no menor que la
  cadencia más corta.
- `main.py`: entrada del contenedor. Sale con 2 si la configuración o el
  deployment son inválidos; con 1 si se pierde el enlace serie
  (`meshtastic.connection.lost`: el monorepo no lo escuchaba, y un USB
  desconectado dejaba el contenedor vivo y sin datos). SIGTERM → reporte final.
  Reporte JSON cada 10 min.
- Tests: `test_deployment.py` (17), `test_config.py` (12, incluye `main.py` como
  subproceso), `test_receiver.py` (22: guardias de filtrado, paquetes
  malformados y los 7 de `TestPdrIntegration` del monorepo, más hold, G10 y
  fallos). **171 en verde.** Mutaciones del receiver: 7/7 detectadas.
- Equivalencia por escenario (24 eventos, relojes controlados: pérdidas,
  temprano, 2 sweeps, reboot, duplicado, mensajes, desconocido, flujo sin
  cadencia, telemetría sin hora) contra el `MeshReceiver` real: 25
  publicaciones en ambos, **24/25 idénticas**; la diferencia es el hold de
  `device_ts`.
- `.env.example` completo; `deployments/README.md` (los warnings);
  GATEWAY-DIRECTIVES §3 y §6.

### Decisions
- Lo que puede apuntar a la malla, el espacio de tópicos o la radio
  equivocados es obligatorio; lo inocuo tiene default.
- Los paquetes propios se descartan antes de contarse como oídos. El chequeo
  exige id no nulo (el monorepo descartaba si ambos eran `None`).
- `capture_content` no se expone por entorno (el monorepo tampoco lo hacía).

### Outcomes
- Paso 4: código y tests listos; falta la comprobación con una radio real.

### Next steps / open questions
- Usuario: comprobar con una radio real (puede hacerse con el compose del paso 5).
- Paso 5: Dockerfile (`main.py`, `gateway/`, `deployments/` en `/app`) y
  compose; Telegraf y el ACL con `MQTT_TOPIC_PREFIX` (G4);
  `init-credentials.sh`; `docs/troubleshooting.md` con G5 primero.
- NaN en una métrica: hoy es un error contado y el paquete no se publica.
  Decidir si `to_payload` lo trata como ausente.

---

## 2026-10-26 — Paso 3: `publish.py` con prefijo en `.env`
**Time:** 16:00–16:05 (aprox)
**User request:** "sí, que sea .env": el prefijo de tópico (y los parámetros
del PDR) van en `.env`, no en `deployments/`.

### Actions taken
- `requirements.txt` (`paho-mqtt==2.1.0`, el pin del monorepo) y `.venv` del
  gateway. Los tests ahora corren con `.venv/bin/python`.
- `gateway/publish.py`, desde `src/gateway/mqtt_connector.py`:
  - `topic_for(prefix, label, kind)`: `kind` solo de `KINDS` (los seis de §1.3);
    prefijo y label deben ser un único nivel de tópico (sin `/ + #` ni espacios).
  - `topic_prefix_from_env()`: `MQTT_TOPIC_PREFIX` obligatorio, sin default, sin
    recortar espacios (recortado aquí y no en Telegraf divergirían en silencio).
  - `MQTTConnector(broker, topic_prefix, ...)` + `publish_payload(label, kind,
    payload)` en lugar de las cinco `publish_env/device/...` (el receiver se
    reescribe igual; `env` vs `environment` era una trampa).
  - Verificado en el código de paho 2.1.0: con QoS 1, `MQTT_ERR_NO_CONN` deja el
    mensaje encolado y paho lo reenvía al reconectar. El monorepo lo imprimía
    como `ERROR publishing`. Ahora: `queued` (se enviará) y `dropped` (se
    perdió), contados por tópico, para que el receiver los reporte.
  - Rechazo de CONNACK por credenciales (134/135) nombra la causa G5 en el log y
    en el `RuntimeError` de `wait_until_connected`.
  - `json.dumps(allow_nan=False)`: un NaN levanta error en vez de publicar JSON
    inválido que Telegraf descartaría entero.
- `tests/test_publish.py` (14 tests): los tres de formato de tópico diferidos del
  monorepo (ahora los seis kinds), prefijo, ruteo con cliente falso, encolado vs
  descarte, NaN, G5. Seis mutaciones (default de prefijo, trim, NO_CONN como
  pérdida, NaN, sin pista G5, cualquier kind): todas rompen tests.
- `.env.example` con `MQTT_TOPIC_PREFIX`.
- GATEWAY-DIRECTIVES: §0.1 (qué va en `.env` y por qué), §1.3 (`{prefix}`), §3,
  §6 paso 3 hecho.
- **120 tests en verde.**

### Decisions
- Prefijo de un solo nivel. Más simple de sustituir en Telegraf y en el ACL.
- Los parámetros del PDR se agregan a `.env.example` cuando el receiver los lea
  (paso 4), no antes: una variable documentada que nadie lee engaña.

### Next steps / open questions
- Paso 5 (G4): `telegraf.conf`, el ACL de Mosquitto y `init-credentials.sh`
  tienen `meshtastic-testbed` literal; deben usar `MQTT_TOPIC_PREFIX` (Telegraf
  admite `${VAR}`; el ACL hay que generarlo). En compose, `${MQTT_TOPIC_PREFIX:?}`
  para que falte = error.
- Paso 6: `SUBSCRIBE_TOPIC` del dashboard, derivado del mismo prefijo.
- Paso 4: un NaN en una métrica ahora levanta `ValueError` al publicar; el
  receiver debe contarlo y reportarlo (o `to_payload` tratar NaN como ausente:
  decidir con el usuario si aparece).

---

## 2026-10-26 — Paso 2: `CadencePdrTracker`
**Time:** 15:50–16:00 (aprox)
**User request:** "ok" a la recomendación de terminar el proyecto en orden,
empezando por el paso 2 de §6: portar el tracker intacto, sus tests y su
documento de diseño.

### Actions taken
- `gateway/pdr.py`: la clase extraída de `src/gateway/mesh_receiver.py`
  (líneas 38–178); `diff -w` contra el monorepo: idéntica. Solo se agrega el
  docstring del módulo.
- `tests/test_pdr_tracker.py`: copia; el diff contra el monorepo es solo el
  bloque `sys.path`/import y dos líneas del docstring. **26 tests sin cambios en
  verde (G7)**, incluida la regresión del flag `restart`.
- Los golden de telemetría del paso 1 ahora usan el snapshot del tracker real
  (antes: el literal `FIRST_RX_PDR` pasado como entrada). `golden.py` registra
  `CADENCE` y `PDR_WINDOW_SEC` con que se capturaron (los defaults del monorepo).
  Cubre el `TestPdrWindowSlots` diferido.
- `test_payload_contract.py`: `cadence_violated` es int en primera recepción,
  en horario, temprana y en sweep, pasando por `to_payload()` (el test diferido
  del monorepo). Va aquí para no alterar el archivo portado.
- `docs/architecture/pdr-cadence-tracker.md` portado (en castellano a
  propósito). 9 correcciones de referencias obsoletas: rutas;
  `mesh_config.json` → `deployments/`; el provisioning es de la plataforma;
  `SEEN_MAX` (el documento decía 200, el código usa 50); `FRAME_HAS_SEQ` no
  existe (el byte VERSION es el mecanismo); referencias. Nota agregada:
  `pdr_cfg` no puede ir en `deployments/` (lector estricto de la plataforma +
  archivo idéntico en ambos repos).
- Mutaciones de los invariantes de §2 (`floor`, sin `restart`, PDR con un
  paquete, booleano, doble cobro del sweep): las cinco rompen tests.
- **106 tests en verde.** GATEWAY-DIRECTIVES §6: paso 2 marcado hecho.
- Bitácora: se quitaron las horas estimadas de las rondas de la entrada
  anterior; eran posteriores a la hora real.

### Decisions
- Ni una línea de lógica cambiada (directiva §2).

### Outcomes
- G7 cumplido.

### Next steps / open questions
- Paso 3: dónde va el prefijo de tópico — `.env` (recomendado) o una sección
  `gateway` en el formato de deployment de la plataforma. Preguntar.
- Paso 4, además de lo ya listado: el lector debe dividir las cadencias por
  `meta.cadence_scale` (banco); ubicación de `pdr_cfg` (`window_sec`,
  `sweep_interval_sec`), con la misma restricción que el prefijo; el reloj
  monotónico lo garantiza el receiver; tests diferidos de `TestPdrIntegration`
  (reboot por uptime, sweep publica en `.../pdr`, dedup no infla PDR, flujos
  separados, sin cadencia → sin PDR).

---

## 2026-10-26 — Cómo depende el gateway de la plataforma (§0.1)
**Time:** 14:30–15:50 (aprox)
**User request:** generar `meshtastic-gateway` (repo vacío). Primera tarea:
resolver GATEWAY-DIRECTIVES.md §0.1 — cómo depender de una plataforma que no
se instala — presentando opciones y preguntando, sin implementar. Después, si
se aprueba, paso 1 de §6 (tests del contrato publicado) en paralelo.

### Actions taken
- Leídos GATEWAY-DIRECTIVES.md (completo) y REFACTOR-PLATFORM-GATEWAY.md (§0–§1).
- Inspección de solo lectura de `../meshtastic-platform`: CLAUDE.md, memoria
  `no-install-entry-scripts`, `decode/__init__.py`, `registry/loader.py`,
  `tests/test_hard_rules.py`, `.github/workflows/ci.yml`, `.gitmodules`.
- Prueba en scratchpad (sin escribir bytecode en la plataforma): importar
  `meshtastic_platform` desde fuera de su clon, vía symlink y vía copia.

### Decisions
- Ninguna de arquitectura: pendiente de respuesta del usuario.
- Convención de bitácora tomada del CLAUDE.md de la plataforma (el gateway aún
  no tiene CLAUDE.md).

### Outcomes
- `registry.deployments_dir()` resuelve `deployments/` relativo al clon de la
  plataforma (`Path(__file__).resolve().parents[2]`). Vía symlink al paquete de
  un clon: encuentra los 3 deployments. Vía copia del paquete: `available()`
  devuelve `[]` sin error. Una copia vendorizada o instalada con pip pierde el
  registro en silencio salvo que se fije `MESH_DEPLOYMENTS_DIR`.
- `decode` + `registry` importan solo stdlib + pyyaml; no cargan `meshtastic`.
- La plataforma tiene 0 commits: no hay commit que fijar en un submódulo todavía.
- El CLAUDE.md de la plataforma anuncia `meshtastic-gateway` como submódulo en
  su `external/`. Si el gateway a su vez fija la plataforma como submódulo, los
  submódulos quedan mutuos: `--recurse-submodules` anida clones.
- Discrepancias con los documentos: el test de la regla de dependencia se llama
  `tests/test_hard_rules.py` (no `test_dependency_rule.py`); `FUNCTIONS` ya
  incluye `"pbx"`, así que la premisa de §5 cambió (§5 sigue diferido, no se toca).

### Respuesta del usuario
- **Submódulo**: sí. La plataforma se fija como submódulo del gateway.
- **Sin `sys.path` ni `PYTHONPATH`**: la arquitectura son contenedores Docker
  que corren un `main.py` (caso receiver). Cada imagen coloca
  `meshtastic_platform/` (y `deployments/`) al lado de su `main.py`, como ya
  hace `monitor/Dockerfile` del monorepo con `common/`. Verificado: con
  `deployments/` junto al paquete, `_REPO_ROOT` (= `parents[2]`) lo encuentra.
- **La plataforma contiene a ambos** (`meshpbx` y `meshtastic-gateway`) y
  tendrá secciones de integración (membresía) para cada uno. Interpretado como
  submódulos mutuos → regla: nunca `--recurse-submodules`; CI del gateway con
  `submodules: true`, no `recursive`. **Por confirmar con el usuario.**
- **Paso 1 aprobado.**

### Paso 1 de §6 — contrato publicado
- `git ls-remote` de OF306PUC/meshtastic-platform: el remoto existe pero está
  vacío → el submódulo no se puede agregar todavía. El paso 1 avanzó igual.
- Creado `gateway/payload.py`: `to_payload()` (telemetría), `to_message_payload()`
  y `parse_pbx_frame()` (tramas PBX: el decoder de la plataforma deja
  PRIVATE_APP opaco por decisión; decodificarlas es del gateway). Puros: el
  llamador pasa `received_at` y el snapshot de PDR.
- `tests/fixtures/packets.py`: copia literal del monorepo. `tests/fixtures/golden.py`:
  dicts esperados — telemetría desde `test_decode_golden.py` del monorepo;
  mensajes **capturados ejecutando su `MeshReceiver`** sobre los mismos fixtures.
- `tests/test_payload_golden.py` (igualdad exacta de dicts, más estricto que el
  `VOLATILE` del monorepo) y `tests/test_payload_contract.py` (regresiones de
  `test_mesh_receiver.py` que son del payload). **44 tests en verde** en una
  estructura tipo imagen (scratchpad: paquete de la plataforma copiado al lado).
- Sin la plataforma al lado: `ModuleNotFoundError` (falla ruidosa, no silencio).
- **Equivalencia contra el monorepo**: 37 casos (telemetría, hops, mensajes
  válidos/malformados/v2/no-bytes, capture_content) pasados por su
  `_on_receive` real y por `decode()`→`to_payload()`: 35 idénticos; las 2
  diferencias son exactamente D1 (`hop`) y D2 (`snr`).
- Mutaciones (renombrar `humidity`, `malformed` bool, omitir `dst_id`, publicar
  ausentes): las cuatro rompen tests.
- `.gitignore` mínimo (G9: `.env`, `configuration.env`, `mqtt/pwfile`).

### Decisiones del paso 1
- **D1/D2 con la semántica nueva** (hop = hopStart si falta hopLimit; snr 0.0
  si falta rxSnr), como pide la memoria `protobuf3-absent-means-zero` de la
  plataforma. Los tests del monorepo que esperaban `None` codificaban el bug.
- **`device_ts` conserva el respaldo del monorepo** (hora del host = `received_at`
  si el nodo no manda `time`), fijado por un test con nombre. Es un valor
  fabricado; cambiarlo cambia valores publicados → decisión del usuario.
- `to_payload`/`to_message_payload` lanzan `ValueError` si se les pide un flujo
  o portnum que el paquete no trae, en vez de publicar algo vacío.
- `label` se pasa explícito, no se lee de `decoded.node`: el payload no depende
  de la forma interna del `Node` del registro (G8).

### Segunda respuesta del usuario
- **Corrige la interpretación anterior: no hay submódulos mutuos.** Solo la
  plataforma contiene al gateway (`external/meshtastic-gateway`); el gateway NO
  lleva `external/meshtastic-platform`. El gateway tiene además su propio
  `deployments/` para configurarlo por sí solo.
- **`device_ts`: no publicar la hora del host; mantener el valor previo.**

### Acciones (segunda ronda)
- `to_payload(..., held_device_ts=)`: sin hora en el paquete publica el
  `device_ts` previo del flujo que guarda el llamador; sin previo, lo omite.
  Nunca `received_at`. `TestDeviceTs` reescrito (5 tests). **47 tests en verde.**
- Equivalencia contra el monorepo: 33/37 idénticos; las 4 diferencias son las
  deliberadas — D1, D2 y `device_ts` (telemetría sin `time` y posición vacía,
  donde el monorepo ponía la hora del host).
- `deployments/README.md`: para qué es el directorio propio y la regla de no
  duplicar un deployment en ambos lados.
- Verificado: los tests corren sin `sys.path` desde la raíz de la plataforma,
  `python -m unittest discover -s ../meshtastic-gateway/tests -t ../meshtastic-gateway`
  (47 OK; `-t` va primero en el path, así que `tests` es el del gateway).
  Docker Compose v2.40 soporta `additional_contexts`.

### Tercera respuesta del usuario
- **Rechaza copiar `meshtastic_platform/` desde un checkout** (`PLATFORM_DIR`).
  El gateway es un contenedor Docker cuya configuración y parámetros del
  receiver vienen de su `deployments/` y de un `.env`.
- **El submódulo en la plataforma es referencial** (para que cada usuario lo
  encuentre ahí), no un mecanismo de build. El emparejamiento
  plataforma-gateway se hace solo por la membresía en los deployments.
- **Los commits los hace el usuario.**

### Acciones (tercera ronda)
- `deployments/README.md` corregido: decía que dentro de la plataforma mandaban
  los deployments de la plataforma; ahora dice que el contenedor se configura
  con este directorio + `.env` y que la membresía empareja con la plataforma.
- Memoria actualizada (dependencia; el usuario hace los commits).

### Cuarta respuesta del usuario
- **B: el gateway tiene su propio decoder y lector de YAML**, "así el gateway
  puede adaptar ese decode para sus necesidades". Rechazada A (traer la
  plataforma desde su remoto git en el build).
- Deployments duplicados en ambos repos: **documentar, con warning donde se pueda.**

### Acciones (cuarta ronda)
- `gateway/decode.py`: fork literal de `meshtastic_platform/decode/__init__.py`;
  solo cambia el docstring (procedencia, "no se mantienen sincronizados", quién
  parsea PRIVATE_APP). Se portó sin adaptar para que cada adaptación futura sea
  un cambio visible por separado.
- Portados `tests/test_decode.py` y `tests/test_decode_golden.py` de la
  plataforma (imports y dos docstrings ajustados). Funcionan con los fixtures
  del monorepo, que son un superconjunto de los de la plataforma.
- `payload.py` y los tests importan `gateway.decode`. `tests/test_hard_rules.py`:
  prohíbe importar `meshtastic_platform` y tocar `sys.path`; verificado que
  falla si se reintroduce el import.
- **79 tests en verde desde la raíz del gateway, sin la plataforma en el path.**
  Equivalencia contra el monorepo con el decoder propio: 33/37, las mismas 4
  diferencias deliberadas.
- `deployments/README.md`: qué falla en silencio si la copia diverge y el
  chequeo por SHA-256 (el mismo hash de bytes que la plataforma registra en
  `session.json` de channel_study).

### Quinta respuesta del usuario: "Sí, corrige" GATEWAY-DIRECTIVES.md
- Versión 1.1. Encabezado: sin dependencia de código de la plataforma; este
  archivo prevalece sobre REFACTOR-PLATFORM-GATEWAY.md (que no se tocó: es copia
  del documento de la plataforma).
- §0 frase central reescrita. §0.1 pasa de "decidir primero" a **resuelto**: la
  decisión, sus cuatro puntos, la tabla de opciones rechazadas y el costo
  aceptado (dos decoders a propósito). Tabla de frontera: cada lado con su
  propio `decode()`; ambos `test_hard_rules.py`.
- Nuevo §1.2b: las tres diferencias deliberadas de valores frente al monorepo
  (D1 `hop`, D2 `snr`, `device_ts`).
- §1.3: prefijo de tópico desde la configuración propia. §3: filas para
  `decode.py`, `payload.py`, `deployments/`. §3.1: el snippet usa
  `gateway.decode`, `decoded.flows` (propiedad, no método) y el hold de
  `device_ts`; el inspector es el de la plataforma, ejecutado allá.
- §4: G6 y G8 reescritos; nuevos G3c (`device_ts` nunca es el reloj del host) y
  G10 (deployment idéntico a la copia de la plataforma, con los warnings).
- §5: nota con el estado actual de la plataforma (`pbx` ya está en `FUNCTIONS`),
  marcada como hecho, no como resolución; §5 sigue diferido.
- §6: el gateway no espera a la plataforma; paso 1 marcado hecho; paso 4
  ampliado (lector de deployments, hold, warnings G10).
- 79 tests siguen en verde.

### Next steps / open questions
- Del lado de la plataforma (no se toca desde aquí): su CLAUDE.md y su memoria
  `no-install-entry-scripts` dicen que el gateway reutiliza su código como
  submódulo; ya no es así.
- Paso 4 — warnings de deriva de deployments, a implementar en el receiver:
  al arrancar, imprimir el sha256 del archivo con la instrucción de compararlo
  con la copia de la plataforma; en marcha, advertir por remitentes
  desconocidos (DecodeStats), `cadence_violated` y flujos recibidos sin cadencia
  declarada.
- Paso 4: lector de YAML propio (subconjunto: nodos, `node_id`, label,
  `intervals`); estricto en lo que lee, falla ruidosamente.
- El hold de `device_ts` (dict por `(node_id, flujo)`) vive en el receiver:
  test pendiente en el paso 4.
- Tests del monorepo **diferidos** a su paso (no perder):
  - paso 2 (tracker): `cadence_violated` es int; `TestPdrWindowSlots`;
    `TestPdrIntegration` ×7 (reboot, sweep, dedup no infla PDR, flujos separados).
  - paso 3 (publish): formato de tópicos ×3 (`TOPIC_ENV/DEVICE/POSITION`).
  - paso 4 (receiver): `TestFilteringGuards` (desconocido, loopback id/num,
    dedup), `TestMalformedPackets` (None, {}, NODEINFO, sin `decoded`),
    `received_at` reciente.
- Paso 4: el receiver debe contar (DecodeStats) lo no publicado: remitentes
  desconocidos, variantes de telemetría no mapeadas, portnums ignorados; y los
  campos `extra` de métricas nuevas, que `to_payload` no publica.
- Cómo corren los tests fuera de la imagen (CI y local) sin `sys.path`: se
  decide al agregar el submódulo.
