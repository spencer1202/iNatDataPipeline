import pytest

from taxa import TaxonCacheBuilder

def test_build_cache():
    builder = TaxonCacheBuilder("../config.ini")
    print(builder.config)