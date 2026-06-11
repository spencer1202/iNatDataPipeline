# import json
# import pytest
# import requests

# from inatdatapipeline.client import ( 
#     authentication,
#     observations
# )

# INAT_V2_OBSERVATIONS    = "https://api.inaturalist.org/v2/observations"
# PROJECT_ID              = 247148
# FIELDS_FILE             = "src/inatdatapipeline/obs_fields.json"
# ADMIN_USERNAME          = "wisel"
# NOT_ADMIN_USERNAME      = "hspencer1202"
# ADMIN_OUTPUT            = "docs/output_admin.json"
# NOT_ADMIN_OUTPUT        = "docs/output_not_admin.json"

# def fetch_observations(headers: dict, rison_fields: str) -> dict:

#     params = {
#         "project_id"        : PROJECT_ID,
#         "taxon_geoprivacy"  : "obscured",
#         "geoprivacy"        : "obscured",
#         "quality_grade"     : "research",
#         "order"             : "desc",
#         "order_by"          : "created_at",
#         "fields"            : rison_fields,
#     }
#     response = requests.get(
#         url=INAT_V2_OBSERVATIONS,
#         headers=headers,
#         params=params,
#         timeout=30
#     )
#     response.raise_for_status()
#     return response.json()


# def count_with_private_location(results: list) -> int:
#     return sum(
#         1 for obs in results
#         if obs.get("private_location") and obs.get("private_location") != obs.get("location")
#     )


# def write_json(data: dict, path: str) -> None:
#     with open(path, "w", encoding="latin") as fp:
#         json.dump(data, fp, indent=4, ensure_ascii=False)
    
# # --- Fixtures ------------------------------------

# @pytest.fixture(scope="module")
# def rison_fields() -> str:
#     return observations._get_fields_rison(FIELDS_FILE)


# @pytest.fixture(scope="module")
# def admin_auth() -> authentication.INaturalistAuth:
#     auth = authentication.INaturalistAuth()
#     auth.generate_access_token(ADMIN_USERNAME)
#     return auth

# @pytest.fixture(scope="module")
# def not_admin_auth() -> authentication.INaturalistAuth:
#     auth = authentication.INaturalistAuth()
#     auth.generate_access_token(NOT_ADMIN_USERNAME)
#     return auth

# # --- Tests ------------------------------------
# def test_admin_response_is_valid(admin_auth, rison_fields):
#     data = fetch_observations(admin_auth.get_auth_headers(), rison_fields)
#     assert "results" in data, "Response missing 'results' key"
#     assert isinstance(data["results"], list)


# def test_not_admin_response_is_valid(not_admin_auth, rison_fields):
#     data = fetch_observations(not_admin_auth.get_auth_headers(), rison_fields)
#     assert "results" in data, "Response missing 'results' key"
#     assert isinstance(data["results"], list)


# def test_admin_sees_private_coordinates(admin_auth, rison_fields):
#     data = fetch_observations(admin_auth.get_auth_headers(), rison_fields)
#     results = data.get("results", [])
#     assert results, "No results returned for admin"

#     trusted = count_with_private_location(results)
#     assert trusted > 0, (
#         f"Admin received {len(results)} obscured observations but none had a "
#         "private_location different from location. "
#         "Check JWT exchange, project trust settings, and that observers have opted in."
#     )


# def test_not_admin_lacks_private_coordinates(not_admin_auth, rison_fields):
#     data = fetch_observations(not_admin_auth.get_auth_headers(), rison_fields)
#     results = data.get("resutls", [])

#     trusted = count_with_private_location(results)
#     assert trusted == 0, (
#         f"Non-admin account unexpectedly received private coordinates for "
#         f"{trusted} observation(s)." 
#     )


# def test_export_outputs(admin_auth, not_admin_auth, rison_fields):
#     admin_data = fetch_observations(admin_auth.get_auth_headers(), rison_fields)
#     not_admin_data = fetch_observations(not_admin_auth.get_auth_headers(), rison_fields)

#     write_json(admin_data, ADMIN_OUTPUT)
#     write_json(not_admin_data, NOT_ADMIN_OUTPUT)
