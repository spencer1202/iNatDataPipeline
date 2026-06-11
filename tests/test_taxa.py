from unittest.mock import MagicMock, patch
import logging
import pytest
import datetime
import pandas as pd

from inatdatapipeline.client.taxa import (
    Taxon,
    TaxonResult,
    MappingResult,
    TaxonMappingBuilder
)
from inatdatapipeline.db import DBManager
from inatdatapipeline.client.authentication import INaturalistAuth

# Set up logging
logger = logging.getLogger('pipeline')

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth():
    mock = MagicMock()
    mock.get_auth_headers.return_value = {"Authorization": "Bearer test_token"}
    return mock



@pytest.fixture
def preprocessed_df(tracking_df):
    """Tracking df with sci_name_clean and exact_match already set."""
    df = tracking_df.copy()
    df["sci_name_clean"] = ["Aster alpinus", "Carex stipata", "Salix"]
    df["exact_match"]    = [True, True, False]
    return df


def make_api_response(results: list) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"results": results}
    return mock_response


def make_taxon_result(primary_id=123, primary_name="Carex stipata", alternatives=None):
    alts = [Taxon(t[0], t[1]) for t in (alternatives or [])]
    return TaxonResult(primary=Taxon(primary_id, primary_name), alternatives=alts)

# ---------------------------------------------------------------------------
# preprocess_name
# ---------------------------------------------------------------------------

class TestPreprocessName:
    def test_removes_var(self):
        assert TaxonMappingBuilder.preprocess_name("Plagiochila semidecurrens var. semidecurrens") == "Plagiochila semidecurrens semidecurrens"
    
    def test_removes_ssp(self):
        assert TaxonMappingBuilder.preprocess_name("Sidalcea malviflora ssp. patula") == "Sidalcea malviflora patula"
    
    def test_removes_pop(self):
        assert TaxonMappingBuilder.preprocess_name("Salvelinus confluentus pop. 25") == "Salvelinus confluentus 25"
    
    def test_removes_sp(self):
         assert TaxonMappingBuilder.preprocess_name("Salix sp. 12") == "Salix 12"
        
    def test_plain_binomial_unchanged(self):
        assert TaxonMappingBuilder.preprocess_name("Sardinops sagax") == "Sardinops sagax"

    def test_none_returns_none(self):
        assert TaxonMappingBuilder.preprocess_name(None) is None

    def test_nan_returns_none(self):
        assert TaxonMappingBuilder.preprocess_name(float("nan")) is None
    
    def test_empty_string_returns_none(self):
        assert TaxonMappingBuilder.preprocess_name("") is None
    
    def test_cleans_double_spaces(self):
        result = TaxonMappingBuilder.preprocess_name("Aster  alpinus")
        assert "  " not in result
    

# ---------------------------------------------------------------------------
# get_undescribed_names
# ---------------------------------------------------------------------------

class TestGetUndescribedNames:
    def test_marks_described_taxa_as_exact_match(self):
        df = pd.DataFrame({"sci_name_clean": ["Carex stipata", "Aster alpinus"]})
        result = TaxonMappingBuilder.get_undescribed_names(df)
        assert result["exact_match"].all()

    def test_marks_undescribed_taxa(self):
        df = pd.DataFrame({"sci_name_clean": ["Salix 12", "Carex stipata"]})
        result = TaxonMappingBuilder.get_undescribed_names(df)
        assert not result.loc[0, "exact_match"]
        assert result.loc[1, "exact_match"]
    
    def test_extracts_generic_name(self):
        df = pd.DataFrame({"sci_name_clean": ["Salix 12"]})
        result = TaxonMappingBuilder.get_undescribed_names(df)
        assert result.loc[0, "sci_name_clean"] == "Salix"
    
    def test_preserved_described_name(self):
        df = pd.DataFrame({"sci_name_clean": ["Carex stipata"]})
        result = TaxonMappingBuilder.get_undescribed_names(df)
        assert result.loc[0, "sci_name_clean"] == "Carex stipata"


# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_applies_overrides(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess(tracking_df.copy(), overrides_df)
        assert result.loc[result["est_id"] == 1, "sci_name_clean"].iloc[0] == "Aster alpinus"
        
    def test_non_overriden_names_preprocessed(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess(tracking_df.copy(), overrides_df)
        assert result.loc[result["est_id"] == 2, "sci_name_clean"].iloc[0] == "Carex stipata"
        
    def test_undescribed_taxa_marked(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess(tracking_df.copy(), overrides_df)
        assert not result.loc[result["est_id"] == 3, "exact_match"].iloc[0]

    def test_described_taxa_marked(self, tracking_df, overrides_df):
        result = TaxonMappingBuilder.preprocess(tracking_df.copy(), overrides_df)
        assert result.loc[result["est_id"] == 2, "exact_match"].iloc[0]


# ---------------------------------------------------------------------------
# query_taxon
# ---------------------------------------------------------------------------

class TestQueryTaxon:
    def test_returns_exact_match_as_primary(self, auth):
        api_results = [
            {"id": 123, "name": "Carex stipata"},
            {"id": 456, "name": "Carex stipata var. maxima"}
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)
        
        assert result is not None
        assert result.primary.taxon_id == 123
        assert result.primary.name == "Carex stipata"
        assert all(t.taxon_id != 123 for t in result.alternatives)

    def test_no_exact_match_uses_first_result(self, auth):
        api_results = [
            {"id": 789, "name": "Carex stipata var. maxima"},
            {"id": 101, "name": "Carex stipata subsp. other"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.primary.taxon_id == 789
    
    def test_empty_results_returns_none(self, auth):
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response([])
            result = TaxonMappingBuilder.query_taxon("Nonexistent taxon", auth)

        assert result is None
    
    def test_network_error_returns_none(self, auth):
        import requests as req
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.side_effect = req.RequestException("Network error")
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result is None
    
    def test_invalid_taxon_id_skipped(self, auth):
        api_results = [
            {"id": None, "name": "Carex stipata"},
            {"id": 456,  "name": "Carex stipata var. maxima"},
        ]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result is not None
        assert result.primary.taxon_id == 456
    
    def test_case_insensitive_exact_match(self, auth):
        api_results = [{"id": 123, "name": "carex stipata"}]
        with patch("inatdatapipeline.client.taxa.requests.get") as mock_get:
            mock_get.return_value = make_api_response(api_results)
            result = TaxonMappingBuilder.query_taxon("Carex stipata", auth)

        assert result.primary.taxon_id == 123
    

# ---------------------------------------------------------------------------
# get_new_mappings
# ---------------------------------------------------------------------------

class TestGetNewMappings:
    def test_returns_none_when_no_results(self, preprocessed_df, auth):
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=None):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(preprocessed_df, auth)
        
        assert result is None

    def test_returns_none_when_no_alternative(self, preprocessed_df, auth):
        taxon_result = make_taxon_result(alternatives=[])
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=taxon_result):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(preprocessed_df, auth)
        
        assert isinstance(result, MappingResult)
        assert result.new_mappings is not None
        assert result.alt_names is None

    def test_returns_mapping_result_with_alternatives(self, preprocessed_df, auth):
        taxon_results = [
            make_taxon_result(primary_id=i, alternatives=[(i + 100, f"Alt taxon {i}")])
            for i in range(len(preprocessed_df))
        ]

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=taxon_results):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(preprocessed_df, auth)

        assert isinstance(result, MappingResult)
        assert result.new_mappings is not None
        assert result.alt_names is not None

    def test_undescribed_taxa_queried_once(self, preprocessed_df, auth):
        """The same undescribed taxon name should only be queried onece."""
        df = preprocessed_df.copy()
        df["sci_name_clean"] = ["Salix", "Salix", "Salix"]
        df["exact_match"] = [False, False, False]

        taxon_results = iter([
            make_taxon_result(primary_id=i, alternatives=[(i + 100, f"Salix alt {i}")])
            for i in range(len(df))
        ])

        with patch.object(TaxonMappingBuilder, "query_taxon", side_effect=lambda name, auth: next(taxon_results)) as mock_query:
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                TaxonMappingBuilder.get_new_mappings(df, auth)
        
        assert mock_query.call_count == 1

    def test_last_updated_set_to_today(self, preprocessed_df, auth):
        taxon_result = make_taxon_result(alternatives=[(456, "Carex stipata var. x")])
        with patch.object(TaxonMappingBuilder, "query_taxon", return_value=taxon_result):
            with patch("inatdatapipeline.client.taxa.time.sleep"):
                result = TaxonMappingBuilder.get_new_mappings(preprocessed_df, auth)

        assert (result.new_mappings["last_updated"].dt.date == datetime.date.today()).all()


# ---------------------------------------------------------------------------
# build_mapping
# ---------------------------------------------------------------------------

class TestBuildMapping:
    def test_raises_on_none_or_empty_tracking_df(self, auth):
        builder = TaxonMappingBuilder()
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            builder.build_mapping(pd.DataFrame(), auth, None)
        with pytest.raises(ValueError, match="Tracking dataframe must not be None or empty"):
            builder.build_mapping(None, auth, None)
        
    def test_filters_already_mapped_taxa(self, preprocessed_df, auth):
        builder = TaxonMappingBuilder()
        mapping_df = pd.DataFrame({"est_id": [1, 2]})

        with patch.object(TaxonMappingBuilder, "get_new_mappings", return_value=MappingResult()) as mock_get:
            builder.build_mapping(preprocessed_df, auth, mapping_df)
        
        called_df = mock_get.call_args[0][0]
        assert len(called_df) == 1
        assert called_df.iloc[0]["est_id"] == 3

    def test_returns_none_when_all_already_mapped(self, preprocessed_df, auth):
        builder = TaxonMappingBuilder()
        mapping_df = pd.DataFrame({"est_id": [1, 2, 3]})
        result = builder.build_mapping(preprocessed_df, auth, mapping_df)
        assert result is None

    def test_none_mapping_df_maps_all_taxa(self, preprocessed_df, auth):
        builder = TaxonMappingBuilder()

        with patch.object(TaxonMappingBuilder, "get_new_mappings", return_value=MappingResult()) as mock_get:
            builder.build_mapping(preprocessed_df, auth, None)
        
        called_df = mock_get.call_args[0][0]
        assert len(called_df) == 3