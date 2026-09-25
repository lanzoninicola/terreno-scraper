from . import olx, generic, single_listing, chavesnamao

PARSERS = {
    "olx": olx.parse,
    "generic": generic.parse,
    "imovelweb": generic.parse,
    "zap": generic.parse,
    "chavesnamao": chavesnamao.parse,
    "imb": generic.parse,
    "trovit": generic.parse,
    "single_listing": single_listing.parse,
}


def get_parser(platform: str):
    return PARSERS.get(platform, generic.parse)
