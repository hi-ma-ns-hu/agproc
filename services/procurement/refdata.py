from functools import lru_cache
from pathlib import Path

import yaml

_CURR_DIR = Path(__file__).parent
_SAMPLE_REFDATA = _CURR_DIR / 'refdata.sample.yml'
_REAL_REFDATA = _CURR_DIR / 'refdata.yml'


@lru_cache(maxsize=1)
def load_refdata() -> dict:
  """
  Load reference data once per process.
  """
  path = _REAL_REFDATA if _REAL_REFDATA.exists() else _SAMPLE_REFDATA
  with open(path, encoding='utf-8') as f:
    return yaml.safe_load(f)


def clear_refdata():
  """
  Clear refdata cache and force the next load_refdata() call to re-read from disk after editing refdata without restarting.
  """
  load_refdata.cache_clear()


def crop_config(crop: str, refdata: dict) -> dict | None:
  """
  Get crop's config entry. We don't store the details of crops we don't buy.
  """
  return refdata.get('crops', {}).get(crop)
