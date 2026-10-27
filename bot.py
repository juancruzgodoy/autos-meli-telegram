"""Monitor conservador: no envía avisos sin fecha de publicación verificable.

El acceso se valida por separado en cada entorno: MeLi puede bloquear servidores.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_CEILING
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc


class BotError(Exception):
    pass


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value.lower()).strip()


def money(value):
    """Número mostrado en español; nunca convertir cuotas o símbolos en precios."""
    raw = re.sub(r"[^\d.,]", "", str(value))
    if not raw:
        return None
    try:
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def published_recently(text, now, hours=24):
    """Usa el extremo más antiguo del intervalo mostrado, no la primera detección.

    'hace 23 horas' representa [23,24) horas; 'hace 1 día' es ambiguo y se descarta.
    'hoy' también se descarta porque puede significar fecha de renovación.
    """
    exact = stamp(text)
    if exact:
        age = now - exact
        return timedelta(0) <= age <= timedelta(hours=hours)
    text = normalize(text)
    if re.search(r"publicado\s+hace\s+un\s+instante", text):
        return True
    match = re.search(r"publicado\s+hace\s+(\d+|un|una)\s+(minuto|hora|dia)s?", text)
    if not match:
        return False
    amount = 1 if match[1] in ("un", "una") else int(match[1])
    unit = {"minuto": 1 / 60, "hora": 1, "dia": 24}[match[2]]
    return (amount + 1) * unit <= hours


def valid_meli_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in {
        "autos.mercadolibre.com.ar", "auto.mercadolibre.com.ar",
        "vehiculo.mercadolibre.com.ar", "listado.mercadolibre.com.ar"
    } and not parsed.username and parsed.port in (None, 443))


def canonical(url):
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def item_id(url):
    match = re.search(r"\bMLA-?(\d+)\b", url)
    return "MLA" + match[1] if match else None


def place_allowed(location, config):
    # Comparación de componentes, no subcadenas: Mar del Plata != La Plata.
    parts = re.split(r"\s+-\s+|,|\||\n", normalize(location))
    return bool(set(parts) & {normalize(p) for p in config["allowed_places"]})


@dataclass
class Car:
    id: str
    title: str
    year: int | None
    km: int | None
    price: Decimal | None
    currency: str | None
    location: str
    url: str
    published: str = ""


def eligible(car, config, rate, now, check_date=True):
    if not car.id or not car.title:
        return False, "datos_incompletos"
    if car.year is None or not config["min_year"] <= car.year <= now.year + 1:
        return False, "año"
    if car.km is None or not 0 <= car.km < config["max_km_exclusive"]:
        return False, "km"
    if not place_allowed(car.location, config):
        return False, "zona"
    if car.currency not in ("ARS", "USD") or car.price is None or car.price <= 0:
        return False, "precio_desconocido"
    if car.currency == "USD" and rate is None:
        return False, "sin_cotizacion"
    ars = car.price * (rate if car.currency == "USD" else Decimal(1))
    if not Decimal(config["min_price_ars"]) <= ars <= Decimal(config["max_price_ars"]):
        return False, "precio"
    if check_date and not published_recently(car.published, now, config["max_age_hours"]):
        return False, "fecha_no_verificada_o_antigua"
    return True, "ok"


def text_of(root, selector):
    element = root.select_one(selector)
    return element.get_text(" ", strip=True) if element else ""


def year_km(text):
    y = re.search(r"\b(20\d{2}|19\d{2})\b", text)
    k = re.search(r"\b([\d.]+)\s*km\b", text, re.I)
    return int(y[1]) if y else None, int(k[1].replace(".", "")) if k else None


def parse_price(root):
    fraction = text_of(root, ".andes-money-amount__fraction")
    symbol = text_of(root, ".andes-money-amount__currency-symbol")
    cents = text_of(root, ".andes-money-amount__cents")
    value = money(fraction + ("," + cents if cents else ""))
    currency = "USD" if symbol in ("US$", "U$S", "USD") else "ARS" if symbol == "$" else None
    return value, currency


def parse_search(html, url):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        if soup.select_one(".ui-search-rescue") and re.search(
            r"no (hay|encontramos) (publicaciones|resultados)", normalize(soup.get_text(" "))
        ):
            return [], None
        raise BotError("MeLi: HTML sin tarjetas reconocibles; posible bloqueo o cambio de diseño.")
    result = []
    for card in cards:
        link = card.select_one("a.poly-component__title, a.ui-search-link")
        if not link or not valid_meli_url(link.get("href", "")):
            continue
        href = canonical(link["href"])
        ident = item_id(href)
        if not ident:
            continue
        title = text_of(card, ".poly-component__title, .ui-search-item__title")
        attrs = text_of(card, ".poly-component__attributes-list, .ui-search-card-attributes")
        year, km = year_km(attrs)
        price_root = card.select_one(".poly-price__current, .ui-search-price__second-line")
        price, currency = parse_price(price_root) if price_root else (None, None)
        location = text_of(card, ".poly-component__location, .ui-search-item__location")
        result.append(Car(ident, title, year, km, price, currency, location, href))
    if not result:
        raise BotError("MeLi: tarjetas presentes pero no se pudieron extraer avisos; revisar adaptador.")
    following = soup.select_one("li.andes-pagination__button--next a, a[rel=next]")
    next_url = urljoin(url, following["href"]) if following and following.get("href") else None
    if following and "andes-pagination__button--disabled" not in following.parent.get("class", []) and not next_url:
        # MeLi renderiza href vacío y navega con JS. Patrón observado en su navegador.
        match = re.search(r"_Desde_(\d+)", url)
        offset = (int(match[1]) if match else 1) + len(cards)
        next_url = re.sub(r"_Desde_\d+", f"_Desde_{offset}", url) if match else url.replace("_OrderId_", f"_Desde_{offset}_OrderId_", 1)
        if next_url == url:
            raise BotError("Paginación sin URL reconocible; no se puede asegurar cobertura.")
    if next_url and not valid_meli_url(next_url):
        raise BotError("MeLi: enlace de paginación inesperado.")
    return result, next_url


def parse_detail(html, card):
    soup = BeautifulSoup(html, "html.parser")
    # Solo cabecera del aviso: jamás fecha de productos recomendados o pie de página.
    title = text_of(soup, "h1.ui-pdp-title")
    if not title:
        raise BotError("MeLi: ficha sin título; posible bloqueo o cambio de diseño.")
    header = soup.select_one(".ui-pdp-header")
    subtitle_nodes = (header or soup).select(".ui-pdp-subtitle")
    subtitle = " | ".join(node.get_text(" ", strip=True) for node in subtitle_nodes)
    year, km = year_km(subtitle)
    for row in soup.select(".andes-table__row"):
        key = normalize(text_of(row, "th"))
        value = text_of(row, "td")
        if key == "ano" and re.fullmatch(r"\d{4}", value):
            year = int(value)
        if key == "kilometros" and re.fullmatch(r"[\d.]+\s*km", value, re.I):
            km = int(re.sub(r"\D", "", value))
    price_root = soup.select_one(".ui-pdp-price__second-line")
    price, currency = parse_price(price_root) if price_root else (None, None)
    # No se conserva precio de la tarjeta si no se confirma en la ficha.
    location = text_of(soup, ".ui-vip-location__subtitle, .ui-pdp-location__subtitle") or card.location
    return Car(card.id, title, year, km, price, currency, location, card.url, subtitle)


def http(method, url, **kwargs):
    """Errores sin URL/cuerpo para no filtrar tokens de Telegram a logs."""
    try:
        return requests.request(method, url, timeout=(10, 30), **kwargs)
    except requests.RequestException:
        raise BotError("Error de red o timeout; no se completó la operación.") from None


def fetch_html(url):
    if not valid_meli_url(url):
        raise BotError("URL MeLi inválida en configuración o paginación.")
    for _ in range(4):
        response = http("GET", url, headers={"User-Agent": "AutosMeliMonitor/1.0 (personal alerts)"},
                        allow_redirects=False)
        if response.status_code not in (301, 302, 303, 307, 308):
            break
        destination = urljoin(url, response.headers.get("Location", ""))
        if (not valid_meli_url(destination) or destination == url or
                re.search(r"login|challenge|captcha|verification", destination, re.I)):
            raise BotError("MeLi redirige fuera de la búsqueda pública; acceso no validado.")
        url = destination
    if response.status_code != 200:
        raise BotError(f"MeLi HTTP {response.status_code}: acceso no validado; búsqueda interrumpida.")
    return response.text


def blue_rate(config, now):
    response = http("GET", "https://dolarapi.com/v1/dolares/blue")
    if response.status_code != 200:
        raise BotError(f"DolarAPI HTTP {response.status_code}.")
    try:
        data = response.json()
        value = Decimal(str(data["venta"]))
        updated = stamp(data["fechaActualizacion"])
        if (not value.is_finite() or value <= 0 or not updated or
                not timedelta(0) <= now - updated <= timedelta(hours=config["max_fx_age_hours"])):
            raise ValueError()
        return value, data["fechaActualizacion"]
    except (KeyError, ValueError, InvalidOperation):
        raise BotError("DolarAPI: cotización inválida o desactualizada.") from None


def telegram(method, payload):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise BotError("Falta TELEGRAM_BOT_TOKEN o su formato no es válido.")
    response = http("POST", f"https://api.telegram.org/bot{token}/{method}", json=payload)
    try:
        data = response.json()
    except ValueError:
        raise BotError("Telegram: respuesta no válida.") from None
    if response.status_code != 200 or not data.get("ok"):
        raise BotError(f"Telegram rechazó la operación (HTTP {response.status_code}).")
    return data["result"]


def send(text):
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not re.fullmatch(r"-\d+", chat):
        raise BotError("TELEGRAM_CHAT_ID debe ser el ID negativo de tu grupo.")
    return telegram("sendMessage", {"chat_id": chat, "text": text,
                                    "link_preview_options": {"is_disabled": True}})


def number(value):
    return f"{value:,.0f}".replace(",", ".")


def message(car, rate, updated):
    parts = [f"🚘 {car.title[:200]}", f"Año: {car.year}", f"Kilómetros: {number(car.km)} km",
             f"Lugar: {car.location[:180]}", f"Precio: {car.currency} {number(car.price)}"]
    if car.currency == "USD":
        parts.append(f"Equivalente: ARS {number(car.price * rate)} · blue venta {rate}")
        parts.append(f"Cotización actualizada: {updated}")
    parts.extend([f"Publicación: {car.published[:180]}", car.url])
    return "\n".join(parts)


class State:
    """Solo IDs y timestamps. En Actions se guarda tras cada envío en bot-state."""
    def __init__(self, path=None, remote=False):
        self.path = path or ROOT / "state.json"
        self.remote = remote
        self.sha = None
        self.data = {"sent": {}, "checked": {}, "last_error": None}
        if remote:
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                raise BotError("GITHUB_REPOSITORY inválido.")
            self.base = f"https://api.github.com/repos/{repo}"
            ref = self.api("GET", "/git/ref/heads/bot-state", allowed=(200, 404))
            if ref.status_code == 404:
                self.api("POST", "/git/refs", json={"ref": "refs/heads/bot-state",
                                                    "sha": os.environ["GITHUB_SHA"]})
            saved = self.api("GET", "/contents/state.json?ref=bot-state", allowed=(200, 404))
            if saved.status_code == 200:
                result = saved.json()
                self.sha = result["sha"]
                self.data = json.loads(base64.b64decode(result["content"]))
        elif self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(self.data.get("sent"), dict):
            raise BotError("Estado inválido; no se reinicia para evitar duplicados.")
        self.data.setdefault("checked", {})
        if not isinstance(self.data["checked"], dict):
            raise BotError("Estado de fichas inválido.")

    def api(self, method, route, allowed=(200, 201), **kwargs):
        response = http(method, self.base + route, headers={
            "Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""),
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"
        }, **kwargs)
        if response.status_code not in allowed:
            raise BotError(f"No se pudo guardar/leer estado GitHub (HTTP {response.status_code}).")
        return response

    def save(self):
        # 30 días de deduplicación bastan para una ventana de publicación de 24 h.
        cutoff = datetime.now(UTC) - timedelta(days=30)
        self.data["sent"] = {k: v for k, v in self.data["sent"].items()
                             if stamp(v) and stamp(v) >= cutoff}
        self.data["checked"] = {k: v for k, v in self.data["checked"].items()
                                if stamp(v) and stamp(v) >= cutoff}
        content = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        if self.remote:
            body = {"message": "Actualizar estado de avisos", "branch": "bot-state",
                    "content": base64.b64encode(content.encode()).decode()}
            if self.sha:
                body["sha"] = self.sha
            result = self.api("PUT", "/contents/state.json", json=body).json()
            self.sha = result["content"]["sha"]
        else:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.path)


def deliver(car, state, rate, updated, now):
    if car.id in state.data["sent"]:
        return False
    send(message(car, rate, updated))
    # Si el proceso muere después del envío y antes de guardar puede haber duplicado.
    state.data["sent"][car.id] = now.isoformat()
    state.save()
    return True


def search_urls(config, rate):
    # Consulta ambos rangos porque la conversión interna de MeLi puede diferir del blue.
    # La aceptación definitiva siempre se hace con el precio y moneda originales.
    for base in config["search_bases"]:
        for currency, divisor in (("ARS", Decimal(1)), ("USD", rate)):
            low = (Decimal(config["min_price_ars"]) / divisor).to_integral_value(rounding=ROUND_FLOOR)
            high = (Decimal(config["max_price_ars"]) / divisor).to_integral_value(rounding=ROUND_CEILING)
            yield (base + f"desde-{config['min_year']}/_OrderId_AUCTION*STOP"
                   f"_PriceRange_{low}{currency}-{high}{currency}"
                   f"_KILOMETERS_0km-{config['max_km_exclusive']-1}km_NoIndex_True")


def collect(config, rate, now, state=None):
    seen, matches, counts = set(), [], Counter()
    details = 0
    for start in search_urls(config, rate):
        url = start
        pages_seen = set()
        for _ in range(config["max_pages_per_search"]):
            if not url or url in pages_seen:
                break
            pages_seen.add(url)
            cars, following = parse_search(fetch_html(url), url)
            counts["tarjetas"] += len(cars)
            time.sleep(config["request_delay_seconds"])
            for card in cars:
                if card.id in seen:
                    continue
                seen.add(card.id)
                if state:
                    if card.id in state.data["sent"]:
                        continue
                    checked = stamp(state.data["checked"].get(card.id))
                    if checked and now - checked < timedelta(hours=24):
                        continue
                ok, reason = eligible(card, config, rate, now, check_date=False)
                if not ok:
                    counts[reason] += 1
                    continue
                if details >= config["max_details_per_run"]:
                    counts["fichas_pendientes"] += 1
                    continue
                details += 1
                car = parse_detail(fetch_html(card.url), card)
                time.sleep(config["request_delay_seconds"])
                ok, reason = eligible(car, config, rate, datetime.now(UTC))
                counts[reason] += 1
                if ok:
                    matches.append(car)
                elif state:
                    state.data["checked"][car.id] = now.isoformat()
            url = following
        if url:
            counts["busquedas_con_paginas_pendientes"] += 1
    if counts["tarjetas"] and counts["tarjetas"] == counts["año"]:
        raise BotError("No se pudo extraer ningún año válido; revisar selectores HTML.")
    print(json.dumps(dict(counts), ensure_ascii=False))
    if counts["busquedas_con_paginas_pendientes"]:
        print("ADVERTENCIA: cobertura parcial; quedan páginas fuera del límite configurado.")
    if counts["fichas_pendientes"]:
        print("ADVERTENCIA: hay fichas pendientes; se procesarán por lotes en próximas ejecuciones con estado.")
    if counts["fecha_no_verificada_o_antigua"]:
        print("Se descartaron fichas antiguas o sin fecha verificable; no equivalen a avisos nuevos.")
    return matches, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Busca sin enviar ni escribir estado")
    parser.add_argument("--test-telegram", action="store_true")
    parser.add_argument("--sample", action="store_true", help="Diagnóstico limitado a 1 página y 3 fichas por ejecución")
    args = parser.parse_args()
    if args.test_telegram:
        send("✅ Telegram conectado al buscador de autos. Esto no valida aún el acceso a MeLi.")
        print("Mensaje de prueba enviado.")
        return
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.sample:
        if not args.dry_run:
            raise BotError("--sample requiere --dry-run.")
        config["max_pages_per_search"] = 1
        config["max_details_per_run"] = 3
    now = datetime.now(UTC)
    state = None if args.dry_run else State(remote=os.environ.get("GITHUB_ACTIONS") == "true")
    try:
        rate, updated = blue_rate(config, now)
        print(f"Dólar blue venta: {rate}; actualizado: {updated}")
        matches, counts = collect(config, rate, now, state)
    except BotError as error:
        # Una advertencia al grupo por día; la ejecución igualmente falla en Actions.
        if state:
            last = stamp(state.data.get("last_error"))
            if not last or now - last >= timedelta(hours=24):
                send("⚠️ El buscador no pudo completar la consulta. No significa que no haya autos. "
                     "Revisá la ejecución de GitHub Actions. Detalle: " + str(error))
                state.data["last_error"] = now.isoformat()
                state.save()
        raise
    sent = 0
    for car in matches:
        # Revalidar la edad al momento de enviar, por si la consulta fue lenta.
        if not eligible(car, config, rate, datetime.now(UTC))[0]:
            continue
        if args.dry_run:
            print(message(car, rate, updated))
        elif deliver(car, state, rate, updated, datetime.now(UTC)):
            sent += 1
            time.sleep(3.1)  # Menos de 20 mensajes/minuto al grupo.
    if state:
        state.save()
    print(f"Coincidencias verificadas: {len(matches)}. Enviadas: {sent}.")


if __name__ == "__main__":
    try:
        main()
    except (BotError, ValueError, KeyError, OSError) as error:
        # No imprimir traceback de requests: puede contener el token en la URL.
        print(f"ERROR: {error if isinstance(error, BotError) else 'Configuración o estado inválido.'}", file=sys.stderr)
        sys.exit(1)
