"""The learning layer's glossary: plain words for every term the markets page uses, in English and
Spanish, written for World Watch from the SEC's Investor.gov glossary and Banco de México's glossary
(each entry links the one it follows). Definitions explain; none says what to buy, sell or hold.
"""

from __future__ import annotations

INVESTOR_GOV = "https://www.investor.gov/introduction-investing/investing-basics/glossary"
BANXICO = "https://www.banxico.org.mx/divulgacion/glosario/"

# id: (English term, English meaning, Spanish term, Spanish meaning, source)
TERMS: dict[str, tuple[str, str, str, str, str]] = {
    "fix": ("FIX exchange rate",
            "The peso–dollar rate Banco de México sets each bank day from market quotes around midday. Contracts "
            "in Mexico that are paid in dollars use it. It is one official number a day, not a live price.",
            "Tipo de cambio FIX",
            "El tipo de cambio peso-dólar que Banco de México determina cada día hábil con cotizaciones del mercado "
            "cerca del mediodía. Se usa para pagar en México obligaciones en dólares. Es una cifra oficial al día, "
            "no un precio en vivo.", BANXICO),
    "fx-rate": ("Exchange rate",
                "How many units of one currency buy one unit of another. More pesos per dollar means a weaker peso.",
                "Tipo de cambio",
                "Cuántas unidades de una moneda se necesitan para comprar una de otra. Más pesos por dólar significa "
                "un peso más débil.", BANXICO),
    "index": ("Stock index",
              "A number that follows the prices of a chosen group of shares, such as the 500 large US companies "
              "in the S&P 500. You can't buy an index itself; funds that copy it exist.",
              "Índice bursátil",
              "Una cifra que sigue los precios de un grupo elegido de acciones, como las 500 grandes empresas de "
              "EUA del S&P 500. Un índice no se compra directamente; existen fondos que lo replican.", INVESTOR_GOV),
    "vix": ("VIX",
            "Cboe's measure of how much the S&P 500 is expected to swing over the next 30 days, worked out from "
            "option prices. Higher means the market expects bigger moves; it is not a forecast of direction.",
            "VIX",
            "La medida de Cboe de cuánto se espera que oscile el S&P 500 en los próximos 30 días, calculada con "
            "precios de opciones. Más alto significa que se esperan movimientos mayores; no dice hacia dónde.",
            INVESTOR_GOV),
    "dollar-index": ("Broad dollar index",
                     "The Federal Reserve's measure of the dollar against the currencies of the US's main trading "
                     "partners, weighted by trade. It rises when the dollar strengthens.",
                     "Índice amplio del dólar",
                     "La medida de la Reserva Federal del dólar frente a las monedas de los principales socios "
                     "comerciales de EUA, ponderada por comercio. Sube cuando el dólar se fortalece.", INVESTOR_GOV),
    "etf": ("ETF (exchange-traded fund)",
            "A fund that holds a basket of assets and trades on an exchange like a share. EWW holds Mexican "
            "companies and is priced in dollars in New York.",
            "ETF (fondo cotizado)",
            "Un fondo que tiene una canasta de activos y cotiza en bolsa como una acción. EWW tiene empresas "
            "mexicanas y cotiza en dólares en Nueva York.", INVESTOR_GOV),
    "adr": ("ADR (American Depositary Receipt)",
            "A certificate traded in the US that stands for shares of a foreign company. Its dollar price moves "
            "with the company's home price and with the exchange rate.",
            "ADR (recibo de depósito americano)",
            "Un certificado que cotiza en EUA y representa acciones de una empresa extranjera. Su precio en dólares "
            "se mueve con el precio en su país y con el tipo de cambio.", INVESTOR_GOV),
    "crypto": ("Crypto asset",
               "A digital token recorded on a blockchain. Prices can move sharply in hours, and the markets are "
               "less regulated than stock exchanges.",
               "Criptoactivo",
               "Una ficha digital registrada en una cadena de bloques. Su precio puede moverse con fuerza en horas, "
               "y sus mercados están menos regulados que las bolsas.", INVESTOR_GOV),
    "spot": ("Spot price",
             "The price for buying something now, for immediate delivery, as opposed to a futures price agreed "
             "today for a later date.",
             "Precio spot (al contado)",
             "El precio por comprar algo ahora, con entrega inmediata, a diferencia de un precio a futuro pactado "
             "hoy para una fecha posterior.", INVESTOR_GOV),
    "oil": ("WTI, Brent and Henry Hub",
            "Benchmark prices: WTI for US crude oil, Brent for North Sea crude (much of the world's oil is priced "
            "from it), Henry Hub for US natural gas. These are the US Energy Information Administration's daily "
            "spot prices.",
            "WTI, Brent y Henry Hub",
            "Precios de referencia: WTI para el petróleo de EUA, Brent para el del Mar del Norte (base de buena "
            "parte del petróleo del mundo), Henry Hub para el gas natural de EUA. Son precios spot diarios de la "
            "Administración de Información Energética de EUA.", INVESTOR_GOV),
    "policy-rate": ("Policy rate",
                    "The interest rate a central bank sets to steer borrowing costs and inflation: Banco de "
                    "México's target rate, the Federal Reserve's federal funds rate.",
                    "Tasa de política monetaria",
                    "La tasa de interés que fija un banco central para influir en el costo del crédito y en la "
                    "inflación: la tasa objetivo de Banco de México, la de fondos federales de la Reserva Federal.",
                    BANXICO),
    "tiie": ("TIIE",
             "Mexico's interbank equilibrium interest rate, worked out by Banco de México from banks' quotes. Many "
             "loans in Mexico are priced from it.",
             "TIIE",
             "La Tasa de Interés Interbancaria de Equilibrio, que calcula Banco de México con cotizaciones de los "
             "bancos. Muchos créditos en México se fijan a partir de ella.", BANXICO),
    "cetes": ("Cetes",
              "Short-term Mexican federal government bonds, sold at weekly auctions. Their rate shows what the "
              "government pays to borrow for 28 days.",
              "Cetes",
              "Certificados de la Tesorería: bonos de corto plazo del gobierno federal, vendidos en subastas "
              "semanales. Su tasa muestra lo que paga el gobierno por pedir prestado a 28 días.", BANXICO),
    "yield": ("Bond yield",
              "The yearly return a bond pays if held to the end, as a percentage of its price. When bond prices "
              "fall, yields rise.",
              "Rendimiento de un bono",
              "El rendimiento anual que paga un bono si se conserva hasta su vencimiento, como porcentaje de su "
              "precio. Cuando baja el precio de los bonos, sube su rendimiento.", INVESTOR_GOV),
    "percentage-point": ("Percentage point",
                         "The plain difference between two percentages: a rate going from 6.50% to 6.25% fell "
                         "0.25 percentage points (25 basis points), not 0.25%.",
                         "Punto porcentual",
                         "La diferencia simple entre dos porcentajes: una tasa que pasa de 6.50% a 6.25% bajó 0.25 "
                         "puntos porcentuales (25 puntos base), no 0.25%.", BANXICO),
    "delayed": ("Delayed data",
                "A number that is not live: published after the moment it describes. Every number here says when "
                "it is from and when World Watch fetched it.",
                "Datos con retraso",
                "Una cifra que no es en vivo: se publica después del momento que describe. Cada cifra aquí dice de "
                "cuándo es y cuándo la consultó World Watch.", INVESTOR_GOV),
    "paper": ("Practice (paper) portfolio",
              "Trades with play money, priced from real numbers, to learn how holdings move. No order reaches a "
              "broker and no money moves.",
              "Portafolio de práctica",
              "Operaciones con dinero de juego, con precios reales, para aprender cómo se mueven. Ninguna orden "
              "llega a una casa de bolsa y no se mueve dinero.", INVESTOR_GOV),
}


def glossary() -> list[dict]:
    return [{"id": key, "en": en, "en_text": en_text, "es": es, "es_text": es_text, "source": source}
            for key, (en, en_text, es, es_text, source) in TERMS.items()]
