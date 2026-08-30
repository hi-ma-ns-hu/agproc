from .refdata import crop_config as config
from .schema import Measure


def crop_price(crop: str, refdata: dict, grade: str | None = None) -> Measure | dict[str, Measure] | None:
  crop_config = config(crop, refdata)
  if crop_config is None:
    return None

  unit = crop_config.get('price_unit', refdata.get('defaults', {}).get('price_unit'))

  if 'grades' in crop_config:
    if grade and grade in crop_config['grades']:
      return Measure(crop_config['grades'][grade], unit)
    return {g: Measure(p, unit) for g, p in crop_config['grades'].items()}

  return Measure(crop_config['price'], unit)
