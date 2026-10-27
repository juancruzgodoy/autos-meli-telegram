from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import bot

NOW = datetime.now(timezone.utc)
CONFIG = json.loads((bot.ROOT / "config.json").read_text(encoding="utf-8"))
CAR = bot.Car("MLA123456789", "Auto de prueba", 2021, 89999, Decimal(21000000),
              "ARS", "La Plata - Bs.As. G.B.A. Sur",
              "https://auto.mercadolibre.com.ar/MLA-123456789-auto-_JM", "Publicado hace 3 horas")


class Filters(unittest.TestCase):
    def test_price_inclusive_and_km_exclusive(self):
        for price in (20000000, 23000000):
            self.assertTrue(bot.eligible(replace(CAR, price=Decimal(price)), CONFIG, None, NOW)[0])
        for price in (19999999, 23000001):
            self.assertFalse(bot.eligible(replace(CAR, price=Decimal(price)), CONFIG, None, NOW)[0])
        for km in (90000, -1, None):
            self.assertFalse(bot.eligible(replace(CAR, km=km), CONFIG, None, NOW)[0])

    def test_year(self):
        self.assertFalse(bot.eligible(replace(CAR, year=2020), CONFIG, None, NOW)[0])
        self.assertTrue(bot.eligible(CAR, CONFIG, None, NOW)[0])

    def test_usd_conversion(self):
        car = replace(CAR, currency="USD", price=Decimal(14000))
        self.assertTrue(bot.eligible(car, CONFIG, Decimal(1500), NOW)[0])
        self.assertFalse(bot.eligible(car, CONFIG, Decimal(1800), NOW)[0])
        self.assertFalse(bot.eligible(car, CONFIG, None, NOW)[0])

    def test_places(self):
        for place in ("La Plata", "Lanús", "Quilmes", "Palermo - Capital Federal", "City Bell"):
            self.assertTrue(bot.place_allowed(place, CONFIG), place)
        for place in ("Mar del Plata", "Vicente López - Bs.As. G.B.A. Norte", "Morón", "Buenos Aires", ""):
            self.assertFalse(bot.place_allowed(place, CONFIG), place)

    def test_age(self):
        for age in ("Publicado hace 23 horas", "Publicado hace una hora", "Publicado hace 2 minutos"):
            self.assertTrue(bot.published_recently(age, NOW))
        for age in ("Publicado hace 24 horas", "Publicado hace 1 día", "Publicado hoy", "", "Actualizado hace 1 hora"):
            self.assertFalse(bot.published_recently(age, NOW))
        self.assertTrue(bot.published_recently((NOW-timedelta(hours=24)).isoformat(), NOW))
        self.assertFalse(bot.published_recently((NOW-timedelta(hours=24, seconds=1)).isoformat(), NOW))
        self.assertFalse(bot.published_recently((NOW+timedelta(seconds=1)).isoformat(), NOW))
        self.assertFalse(bot.published_recently("2026-10-27", NOW))

    def test_money(self):
        self.assertEqual(bot.money("21.500.000,50"), Decimal("21500000.50"))
        self.assertIsNone(bot.money("Consultar"))


class Parser(unittest.TestCase):
    # Fixtures sintéticas: comprueban el contrato del adaptador, no el HTML real.
    def test_search_card_and_pagination(self):
        html = '''<li class="ui-search-layout__item">
        <a class="poly-component__title" href="https://auto.mercadolibre.com.ar/MLA-123456789-auto-_JM#track">Auto</a>
        <ul class="poly-component__attributes-list"><li>2021</li><li>89.999 Km</li></ul>
        <div class="poly-price__current"><span class="andes-money-amount__currency-symbol">US$</span>
        <span class="andes-money-amount__fraction">14.000</span></div>
        <span class="poly-component__location">La Plata</span></li>
        <li class="andes-pagination__button--next"><a href="/capital-federal/_Desde_49">Siguiente</a></li>'''
        cars, next_url = bot.parse_search(html, "https://autos.mercadolibre.com.ar/capital-federal/")
        self.assertEqual(len(cars), 1)
        self.assertEqual(cars[0].currency, "USD")
        self.assertEqual(cars[0].km, 89999)
        self.assertNotIn("#", cars[0].url)
        self.assertEqual(next_url, "https://autos.mercadolibre.com.ar/capital-federal/_Desde_49")

    def test_no_cards_is_not_silent_success(self):
        with self.assertRaises(bot.BotError):
            bot.parse_search("<h1>Verificá que sos humano</h1>", CAR.url)

    def test_detail_does_not_take_recommended_date(self):
        html = '''<h1 class="ui-pdp-title">Auto</h1><div class="ui-pdp-header">
        <span class="ui-pdp-subtitle">2021 | 89.999 km | Publicado hace 40 días</span></div>
        <div class="ui-pdp-price__second-line"><span class="andes-money-amount__currency-symbol">$</span>
        <span class="andes-money-amount__fraction">21.000.000</span></div>
        <aside>Recomendados: Publicado hace 2 horas</aside>'''
        car = bot.parse_detail(html, CAR)
        self.assertFalse(bot.eligible(car, CONFIG, None, NOW)[0])
        self.assertEqual(car.price, Decimal(21000000))

    def test_missing_price_rejects(self):
        car = bot.parse_detail('<h1 class="ui-pdp-title">Auto</h1><span class="ui-pdp-subtitle">2021 | 80.000 km | Publicado hace 2 horas</span>', CAR)
        self.assertIsNone(car.price)
        self.assertFalse(bot.eligible(car, CONFIG, None, NOW)[0])

    def test_url_scope(self):
        self.assertFalse(bot.valid_meli_url("https://autos.mercadolibre.com.ar.evil.test/"))
        self.assertFalse(bot.valid_meli_url("http://127.0.0.1"))

    def test_js_pagination(self):
        html = '''<li class="ui-search-layout__item"><a class="poly-component__title"
        href="https://auto.mercadolibre.com.ar/MLA-123456789-auto-_JM">Auto</a></li>
        <li class="andes-pagination__button--next"><a href="">Siguiente</a></li>'''
        _, url = bot.parse_search(html, "https://autos.mercadolibre.com.ar/capital-federal/_OrderId_AUCTION*STOP_NoIndex_True")
        self.assertIn("_Desde_2_OrderId_", url)

    def test_both_currencies_in_searches(self):
        urls = list(bot.search_urls(CONFIG, Decimal(1575)))
        self.assertEqual(len(urls), 4)
        self.assertTrue(any("_PriceRange_12698USD-14604USD_" in u for u in urls))
        self.assertTrue(all("_KILOMETERS_0km-89999km_" in u for u in urls))


class IntegrationContracts(unittest.TestCase):
    def test_failed_send_not_marked_and_restart_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = bot.State(path)
            with patch("bot.send", side_effect=bot.BotError("falló")):
                with self.assertRaises(bot.BotError):
                    bot.deliver(CAR, state, None, "", NOW)
            self.assertNotIn(CAR.id, state.data["sent"])
            with patch("bot.send") as send:
                self.assertTrue(bot.deliver(CAR, state, None, "", NOW))
                self.assertFalse(bot.deliver(CAR, bot.State(path), None, "", NOW))
                send.assert_called_once()

    def test_403_explicit(self):
        with patch("bot.http", return_value=Mock(status_code=403)):
            with self.assertRaisesRegex(bot.BotError, "HTTP 403"):
                bot.fetch_html(CAR.url)

    def test_stale_fx(self):
        response = Mock(status_code=200)
        response.json.return_value = {"venta": 1500, "fechaActualizacion": (NOW-timedelta(days=7)).isoformat()}
        with patch("bot.http", return_value=response):
            with self.assertRaisesRegex(bot.BotError, "desactualizada"):
                bot.blue_rate(CONFIG, NOW)

    def test_telegram_api_failure(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": False}
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123:synthetic_test_token"}), patch("bot.http", return_value=response):
            with self.assertRaises(bot.BotError):
                bot.telegram("sendMessage", {})

    def test_message_content(self):
        text = bot.message(replace(CAR, price=Decimal(14000), currency="USD"), Decimal(1500), NOW.isoformat())
        for expected in ("2021", "89.999 km", "La Plata", "21.000.000", CAR.url):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
