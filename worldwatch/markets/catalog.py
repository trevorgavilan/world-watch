"""What the markets page tracks: one Instrument per number, grouped in the order Trevor asked for
(the peso first, then the US, Mexico, crypto, commodities, rates). Each names its source, the
source's own id for it, how late the number is, and the provider's own page (for spot checks).

Banxico and FRED series ids were checked against each provider's own series metadata on the day the
collector was built (FINDINGS); a wrong id would show the provider's title, not ours, in the record.
"""

from __future__ import annotations

from dataclasses import dataclass

GROUPS = [  # (id, English, Spanish), in page order
    ("peso", "The peso", "El peso"),
    ("us", "United States", "Estados Unidos"),
    ("mexico", "Mexico, as traded in New York (USD)", "México, cotizado en Nueva York (USD)"),
    ("watch", "Your watchlist", "Tu lista"),
    ("crypto", "Crypto", "Cripto"),
    ("commodities", "Commodities and metals", "Materias primas y metales"),
    ("rates", "Interest rates", "Tasas de interés"),
]
GROUP_IDS = [g[0] for g in GROUPS]


@dataclass(frozen=True)
class Instrument:
    id: str           # letters, digits and '-': in the page and the raw record
    group: str
    en: str
    es: str
    source: str       # the collector's source name
    key: str          # the source's own id: a Banxico/FRED series, a CoinGecko coin/currency, a ticker
    unit_en: str
    unit_es: str
    decimals: int
    daily: bool       # one number per day (shown with its date), else a moment
    delay_en: str
    delay_es: str
    page: str         # the provider's own page for this number
    term: str = ""    # its glossary entry
    points: bool = False  # a rate: the change is in percentage points, not per cent
    notice: str = ""      # the owner's copyright notice, kept with the number (FRED's terms)


BANXICO_DELAY = ("Official daily rate (FIX), set by Banxico around 12:00 Mexico City time on bank days",
                 "Tipo de cambio oficial (FIX), lo fija Banxico hacia las 12:00 (CDMX) en días hábiles")
FRED_CLOSE = ("Delayed: the previous close, as FRED publishes it (one bank day late or more)",
              "Con retraso: el cierre anterior, como lo publica FRED (un día hábil o más)")
TD_DELAY = ("Delayed: Twelve Data's free plan, the last trade, fetched once an hour; after the bell it can differ "
            "from the exchange's official close by a cent (AMX, 11 Nov: 25.81 here, 25.80 at the NYSE)",
            "Con retraso: plan gratuito de Twelve Data, la última operación, consultada cada hora; tras el cierre "
            "puede diferir un centavo del cierre oficial de la bolsa")
CG_DELAY = ("Delayed: CoinGecko's price, fetched every 15 minutes",
            "Con retraso: precio de CoinGecko, consultado cada 15 minutos")


def _fred(id_, group, en, es, key, unit_en, unit_es, decimals, term="", points=False, notice="") -> Instrument:
    return Instrument(id_, group, en, es, "fred", key, unit_en, unit_es, decimals, True, *FRED_CLOSE,
                      f"https://fred.stlouisfed.org/series/{key}", term, points, notice)


# The series' own notices, as FRED's notes carried them on 2026-11-11: personal use only, kept with the number.
SPDJI = "Copyright © 2016, S&P Dow Jones Indices LLC. All rights reserved. Personal use only."


BANXICO_FIX_PAGE = "https://www.banxico.org.mx/tipcamb/tipCamMIAction.do?idioma=sp"  # the FIX, day by day
BANXICO_RATES_PAGE = "https://www.banxico.org.mx/tipcamb/main.do?page=tas&idioma=sp"  # rates and the last auction


def _banxico(id_, group, en, es, key, unit_en, unit_es, decimals, delay, term="", points=False,
             source="banxico-rates") -> Instrument:
    return Instrument(id_, group, en, es, source, key, unit_en, unit_es, decimals, True, *delay,
                      BANXICO_FIX_PAGE if source == "banxico-peso" else BANXICO_RATES_PAGE, term, points)


def _td(id_, group, en, es, symbol, unit, decimals=2, term="") -> Instrument:
    return Instrument(id_, group, en, es, "twelvedata", symbol, unit, unit, decimals, False, *TD_DELAY,
                      f"https://twelvedata.com/markets/search?query={symbol.replace('/', '')}", term)


def _cg(coin, currency, en, es, decimals) -> Instrument:
    cur = currency.upper()
    return Instrument(f"{coin}-{currency}", "crypto", f"{en} ({cur})", f"{es} ({cur})", "coingecko",
                      f"{coin}/{currency}", cur, cur, decimals, False, *CG_DELAY,
                      f"https://www.coingecko.com/en/coins/{coin}", "crypto")


RATE_DELAY = ("Published by Banxico on the day it applies", "Publicada por Banxico el día que aplica")

INSTRUMENTS: list[Instrument] = [
    _banxico("usd-mxn-fix", "peso", "US dollar in pesos (FIX)", "Dólar en pesos (FIX)", "SF43718",
             "MXN per USD", "MXN por USD", 4, BANXICO_DELAY, "fix", source="banxico-peso"),
    _fred("usd-mxn-noon", "peso", "US dollar in pesos (New York noon)", "Dólar en pesos (mediodía, Nueva York)",
          "DEXMXUS", "MXN per USD", "MXN por USD", 4, "fx-rate"),
    _fred("sp500", "us", "S&P 500", "S&P 500", "SP500", "points", "puntos", 2, "index",
          notice=SPDJI),
    _fred("nasdaq", "us", "Nasdaq Composite", "Nasdaq Composite", "NASDAQCOM", "points", "puntos", 2,
          "index", notice="Copyright © 2016, NASDAQ OMX Group, Inc. Personal use only."),
    _fred("dow", "us", "Dow Jones Industrial Average", "Promedio Industrial Dow Jones", "DJIA", "points", "puntos",
          2, "index", notice=SPDJI),
    _fred("vix", "us", "VIX (expected volatility)", "VIX (volatilidad esperada)", "VIXCLS", "points", "puntos",
          2, "vix", notice="Copyright, 2016, Chicago Board Options Exchange, Inc. Reprinted with permission. "
          "Personal use only."),
    _fred("dollar-index", "us", "Broad dollar index (Fed)", "Índice amplio del dólar (Fed)", "DTWEXBGS",
          "index", "índice", 2, "dollar-index"),
    _td("eww", "mexico", "iShares MSCI Mexico ETF (EWW)", "ETF iShares MSCI México (EWW)", "EWW", "USD", term="etf"),
    _td("amx", "mexico", "América Móvil (AMX)", "América Móvil (AMX)", "AMX", "USD", term="adr"),
    _td("fmx", "mexico", "FEMSA (FMX)", "FEMSA (FMX)", "FMX", "USD", term="adr"),
    _td("cx", "mexico", "Cemex (CX)", "Cemex (CX)", "CX", "USD", term="adr"),
    _td("asr", "mexico", "Grupo Aeroportuario del Sureste (ASR)", "Grupo Aeroportuario del Sureste (ASR)", "ASR",
        "USD", term="adr"),
    _td("pac", "mexico", "Grupo Aeroportuario del Pacífico (PAC)", "Grupo Aeroportuario del Pacífico (PAC)",
        "PAC", "USD", term="adr"),
    _td("omab", "mexico", "OMA airports (OMAB)", "Aeropuertos OMA (OMAB)", "OMAB", "USD", term="adr"),
    _cg("bitcoin", "usd", "Bitcoin", "Bitcoin", 2),
    _cg("bitcoin", "mxn", "Bitcoin", "Bitcoin", 2),
    _cg("ethereum", "usd", "Ether", "Ether", 2),
    _cg("ethereum", "mxn", "Ether", "Ether", 2),
    _cg("solana", "usd", "Solana", "Solana", 2),
    _cg("solana", "mxn", "Solana", "Solana", 2),
    _td("gold", "commodities", "Gold (spot, per troy ounce)", "Oro (spot, por onza troy)", "XAU/USD", "USD",  # silver: not on the free plan (403)
        term="spot"),
    _fred("wti", "commodities", "Crude oil, WTI (per barrel)", "Petróleo WTI (por barril)", "DCOILWTICO", "USD",
          "USD", 2, "oil"),
    _fred("brent", "commodities", "Crude oil, Brent (per barrel)", "Petróleo Brent (por barril)", "DCOILBRENTEU",
          "USD", "USD", 2, "oil"),
    _fred("natgas", "commodities", "Natural gas, Henry Hub (per MMBtu)", "Gas natural, Henry Hub (por MMBtu)",
          "DHHNGSP", "USD", "USD", 2, "oil"),
    _banxico("mx-target", "rates", "Banxico target rate", "Tasa objetivo de Banxico", "SF61745", "%", "%", 2,
             RATE_DELAY, "policy-rate", points=True),
    _banxico("tiie-28", "rates", "TIIE 28 days", "TIIE a 28 días", "SF43783", "%", "%", 4, RATE_DELAY, "tiie",
             points=True),
    _banxico("cetes-28", "rates", "Cetes 28 days (weekly auction)", "Cetes a 28 días (subasta semanal)", "SF60633",
             "%", "%", 2, ("Set at the government's weekly auction, dated by the auction day (usually Tuesday)",
                           "Se fija en la subasta semanal del gobierno; fechado el día de la subasta (normalmente martes)"),
             "cetes", points=True),
    _fred("fed-funds", "rates", "US federal funds rate (effective)", "Tasa de fondos federales (efectiva)", "DFF",
          "%", "%", 2, "policy-rate", points=True),
    _fred("ust-2y", "rates", "US Treasury, 2 years", "Bono del Tesoro EUA, 2 años", "DGS2", "%", "%", 2, "yield",
          points=True),
    _fred("ust-10y", "rates", "US Treasury, 10 years", "Bono del Tesoro EUA, 10 años", "DGS10", "%", "%", 2,
          "yield", points=True),
]


def watch_instrument(symbol: str) -> Instrument:
    """A ticker from Trevor's watchlist (data/markets.txt), fetched from Twelve Data."""
    return _td(f"watch-{symbol.lower().replace('/', '-').replace('.', '-')}", "watch", symbol, symbol, symbol, "USD")


def by_source(source: str, extra: list[Instrument] | None = None) -> list[Instrument]:
    return [i for i in INSTRUMENTS + list(extra or []) if i.source == source]
