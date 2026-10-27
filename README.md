# Autos de MeLi → Telegram

**Estado: lectura web probada localmente y desde GitHub Actions; envío pendiente de configurar Telegram.**
El 27/10/2026 se leyeron 192 tarjetas reales y tres fichas tanto localmente como en una
[ejecución de GitHub Actions](https://github.com/juancruzgodoy/autos-meli-telegram/actions/runs/40577984878),
sin enviar mensajes. También pasaron 18 pruebas automatizadas. Esta muestra limitada
no constituye un recorrido completo de los avisos de las últimas 24 horas.
La API genérica devolvió 403; el adaptador usa búsquedas web con filtros, que sí respondieron.
MeLi puede cambiar el diseño o restringir el acceso en futuras ejecuciones.
El workflow prueba una muestra automáticamente al subir cambios de código a `main`. La programación
permanece desactivada hasta configurar Telegram y activar `MONITOR_ENABLED`.

## Qué hace

- Busca cada 15 minutos cuando se habilita la programación de GitHub Actions.
- Precio total publicado entre ARS 20.000.000 y 23.000.000, límites incluidos.
- USD convertido con **dólar blue venta** de DolarAPI.
- Año 2021 en adelante y menos de 90.000 km (90.000 queda excluido).
- CABA y GBA Sur, incluida La Plata, Berisso y Ensenada. Localidades editables en `config.json`.
- Solo envía fichas con evidencia de publicación dentro de las últimas 24 horas.
- Informa nombre/versión, año, km, ubicación, precio, cotización cuando corresponde y enlace.
- Recuerda los IDs enviados y envía como máximo un aviso de fallo por día.

Se basa en la categoría Autos y Camionetas de MeLi; incluye sus SUVs y pickups. No filtra por marca,
combustible ni transmisión. No verifica el estado mecánico ni que un precio engañoso sea realmente el total.

## 1. Crear tu bot y el grupo de Telegram

1. Abrí [@BotFather](https://t.me/BotFather), el bot oficial de Telegram, y tocá **Iniciar**.
2. Enviá `/newbot`.
3. Para el nombre visible, escribí `Buscador de autos`.
4. Para el nombre de usuario, elegí uno disponible que termine en `bot`, por ejemplo
   `autos_juancruz_alertas_bot` (el ejemplo puede no estar disponible).
5. Guardá el token que te devuelve. Es una contraseña de acceso al bot: no lo publiques
   ni lo pegues en este chat. Si se divulga, revocalo con BotFather.
6. En Telegram creá un grupo, por ejemplo **Autos para comprar**.
7. Agregá a ese grupo el usuario del bot. Solo necesita permiso para enviar mensajes;
   no hace falta darle administración ni desactivar su modo de privacidad.

## 2. Obtener el identificador del grupo

En tu PC, abrí una terminal dentro de esta carpeta. Necesitás Python 3.11 o superior:

```powershell
python -m pip install -r requirements.txt
python configurar_telegram.py
```

El asistente pide el token con entrada oculta, verifica el bot y te indica el comando
`/config@usuario_de_tu_bot` que debés enviar **dentro del grupo**. Después de enviarlo,
presioná Enter en el asistente. Mostrará el `TELEGRAM_CHAT_ID` del grupo, un número negativo.
No guarda el token ni envía mensajes. No lo ejecutes desde Actions ni publiques su salida.

## 3. Subir a GitHub sin pagar

Repositorio: [juancruzgodoy/autos-meli-telegram](https://github.com/juancruzgodoy/autos-meli-telegram).
Si ya contiene los archivos del proyecto, continuá en el paso 4.

Podés conectar el plugin de GitHub para continuar desde este chat. Alternativa manual:

1. Entrá a [crear repositorio](https://github.com/new) con tu cuenta `juancruzgodoy`.
2. Nombre: `autos-meli-telegram`. Visibilidad: **Public**.
3. Subí el contenido de esta carpeta a la raíz del repositorio. No subas el ZIP como único archivo.
4. Confirmá que existe **`.github/workflows/autos.yml`**; algunos métodos de carga omiten
   carpetas ocultas. Podés usar **Add file → Create new file** con ese nombre y copiar su contenido.
5. No subas tokens, `.env`, entornos Python ni la carpeta `__pycache__`.

Los ejecutores estándar Linux son gratuitos en repositorios públicos según la documentación
de GitHub consultada el 27/10/2026. Este proyecto no usa VPS, servicios de scraping pagos,
ejecutores de mayor tamaño, cachés ni artefactos de Actions. En un repositorio privado,
los minutos gratuitos tienen un límite y el mismo horario podría agotarlos.

## 4. Guardar los secretos

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token entregado por BotFather |
| `TELEGRAM_CHAT_ID` | ID negativo del grupo mostrado por el asistente |

No agregues `GITHUB_TOKEN`: Actions lo proporciona automáticamente con permisos
para escribir el estado en la rama `bot-state`. Allí solo se guardan IDs de avisos,
fechas de envío, revisión de fichas y fecha del último aviso de fallo. Al ser público el repositorio,
ese historial también será público. Token y grupo no se escriben allí.

## 5. Probar antes de activar

En **Actions → Buscar autos → Run workflow**:

1. Elegí `probar_telegram`. Debe llegar un mensaje de prueba al grupo.
2. Elegí `diagnostico`. Consulta dólar y una muestra de MeLi (1 página por rango y hasta
   3 fichas en total), pero no envía mensajes ni cambia el estado.
3. Si hay `403`, redirección a verificación o HTML no reconocido, **el buscador aún no funciona**.
   No habilites la programación hasta resolver el acceso o adaptar los selectores.
   No incluye evasión de CAPTCHA, proxies ni promesas de que
   funcionará desde una IP de GitHub. También puede funcionar en tu PC y fallar en la nube.
4. Una ejecución sin excepción tampoco demuestra cobertura completa: revisá el contador
   `tarjetas`, los descartes, las fechas y los mensajes de cobertura parcial. Compará algunas
   fichas reales con su resultado antes de activar envíos.
5. Solo después de esa validación, probá `buscar_y_enviar`.
6. En **Settings → Secrets and variables → Actions → Variables**, agregá
   `MONITOR_ENABLED` con el valor exacto `true`.

La programación queda en los minutos 07, 22, 37 y 52 de cada hora, durante todo el día.
Para detenerla, cambiá `MONITOR_ENABLED` a `false` o deshabilitá el workflow.
El archivo debe estar en la rama predeterminada del repositorio.

GitHub puede demorar u omitir ejecuciones por carga; esto no ofrece garantía de horario
ni de disponibilidad 24/7. En repositorios públicos puede desactivar la programación
tras 60 días sin actividad. Revisá Actions periódicamente y reactivá si corresponde.

## Cómo se verifica “últimas 24 horas”

El adaptador actual lee el subtítulo de la ficha de MeLi. Acepta expresiones como
`Publicado hace 3 horas`, pero descarta `Publicado hace 1 día`, porque podría significar
entre 24 y 48 horas. También descarta `Publicado hoy`, fechas sin hora/zona y campos ausentes.
La función de filtro admite timestamps ISO con zona para futuras fuentes autorizadas;
el adaptador HTML actual no inventa esos timestamps ni toma la fecha de modificación.

**Primera detección no es fecha de publicación.** Se prefieren falsos negativos a avisar
que un anuncio viejo es nuevo. La fecha relativa es la que informa MeLi, no una verificación
independiente de la antigüedad original o de republicaciones.

## Límites de cobertura y mantenimiento

- Los selectores HTML se probaron con fixtures sintéticas y una muestra real descargada
  localmente. Se debe verificar también su comportamiento desde GitHub Actions.
- La interfaz observada ofrece "Fin de publicación", no un orden fiable por fecha de alta.
  Por eso se verifica la antigüedad en cada ficha, sin inferirla del orden de los resultados.
- Se consultan rangos en ARS y USD para CABA y GBA Sur. Hasta 30 páginas por rango y
  120 fichas candidatas por ejecución. Los límites son configurables; no se promete
  cobertura total de MeLi. Las URLs se generan con los filtros observados en su interfaz.
- Las fichas descartadas se recuerdan durante 24 horas, de modo que los lotes siguientes
  avancen sobre otras candidatas. Al comenzar puede requerir varias ejecuciones para
  completar el primer recorrido. Una ficha descartada que se modifique después puede no
  revisarse hasta el día siguiente; una republicación con el mismo ID también puede demorarse.
- Si quedan páginas o fichas, se informa cobertura parcial en los logs. La duración máxima
  del workflow es 20 minutos. La modalidad de diagnóstico no guarda avance entre ejecuciones.
- Cuando MeLi cambia su diseño, una tarjeta incompleta se descarta. Revisar contadores
  evita interpretar errores de extracción como falta de oferta.
- Los avisos ARS y USD se filtran por precio de tarjeta y se revalidan con el precio de ficha.
  Un cambio entre ambas consultas puede producir falsos negativos. No se usan cuotas como precio.
- DolarAPI debe devolver un valor positivo actualizado en las últimas 96 horas (margen para
  fines de semana/feriados). Si falla o envejece, se interrumpe la consulta; no se inventa un cambio.
- El estado se guarda después de cada envío. Un corte entre la entrega a Telegram y el guardado
  puede ocasionar un duplicado en la próxima ejecución. No se promete entrega exactamente una vez.
- Usá una sola instancia y un solo grupo por repositorio; la concurrencia de Actions lo serializa.
- Los avisos de error requieren que Telegram y el guardado de estado estén funcionando.
  Las notificaciones de fallos de GitHub son el respaldo. Un timeout total del runner puede
  impedir enviar la advertencia al grupo.

## Pruebas y ejecución local

```powershell
python -m unittest discover -s tests -v
python bot.py --dry-run
python bot.py --dry-run --sample
```

Para enviar, deben existir las variables de entorno `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
`python bot.py --test-telegram` prueba el grupo; `python bot.py` hace una consulta y termina.
La continuidad la proporciona el horario de Actions. El asistente usa el token solo en su propio
proceso, por lo que no configura esas variables para otros comandos.

## Referencias

- [Telegram: BotFather](https://core.telegram.org/bots/features#botfather)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [GitHub Actions: costos](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Actions: schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [DolarAPI: blue](https://dolarapi.com/docs/argentina/operations/get-dolar-blue)
- [MeLi: búsquedas y acceso](https://developers.mercadolibre.com.ar/es_ar/guia-para-carrito-de-compras/items-y-busquedas)
