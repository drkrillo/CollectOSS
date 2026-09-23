# SPDX-License-Identifier: MIT
import pytest
from unittest.mock import MagicMock, Mock, patch

from collectoss.tasks.github.util import github_graphql_data_access as graphql
from collectoss.tasks.github.util.github_graphql_data_access import (
    GithubGraphQlDataAccess,
    NotFoundException,
)


graphql_query = "{ repository { nameWithOwner } }"
graphql_repository = {"nameWithOwner": "chaoss/CollectOSS", "forkCount": 18,
                      "stargazers": None}

# The unreadable field comes back null, the rest is still populated
graphql_partial_response = {
    "data": {"repository": graphql_repository},
    "errors": [{"type": "FORBIDDEN", "path": ["repository", "stargazers"],
                "locations": [{"line": 1, "column": 94}],
                "message": "Resource not accessible by integration"}],
}
graphql_not_found_response = {
    "data": {"repository": None},
    "errors": [{"type": "NOT_FOUND", "path": ["repository"],
                "message": "Could not resolve to a Repository"}],
}
graphql_clean_response = {
    "data": {"repository": dict(graphql_repository, stargazers={"totalCount": 14})},
}
graphql_responses_that_must_raise = [
    {"data": {"repository": graphql_repository},
     "errors": [{"type": "INTERNAL", "path": ["repository", "stargazers"],
                 "message": "Something went wrong while executing your query"}]},
    {"data": {"repository": graphql_repository},
     "errors": [{"type": "FORBIDDEN", "path": ["repository", "stargazers"],
                 "message": "Resource not accessible by integration"},
                {"type": "INTERNAL", "path": ["repository", "forkCount"],
                 "message": "Something went wrong while executing your query"}]},
    {"errors": [{"type": "FORBIDDEN", "path": ["repository"],
                 "message": "Resource not accessible by integration"}]},
]

def build_data_access(ingore_not_found_error=False):
    logger = Mock()

    with patch("collectoss.tasks.github.util.github_graphql_data_access.KeyClient"):
        data_access = GithubGraphQlDataAccess(Mock(), logger,
                                              ingore_not_found_error=ingore_not_found_error)
    data_access.key = "ghp_1234567890abcdef1234567890abcdef12345678"

    return data_access, logger

def answering_with(graphql_response):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"X-RateLimit-Remaining": "4999"}
    response.json.return_value = graphql_response
    response.raise_for_status.return_value = None

    client = MagicMock()
    client.post.return_value = response
    context = MagicMock()
    context.__enter__.return_value = client

    return patch.object(graphql.httpx, "Client", return_value=context)

@pytest.mark.unit
class TestPartialResponses:

    def test_partial_response_is_returned_and_logged(self):
        data_access, logger = build_data_access()

        with answering_with(graphql_partial_response):
            response = data_access.make_request(graphql_query, {})

        assert response.json() == graphql_partial_response
        logger.warning.assert_called_once()
        logged = logger.warning.call_args[0][0]
        assert "FORBIDDEN" in logged and "stargazers" in logged
        assert "locations" not in logged

    def test_partial_response_keeps_the_fields_that_came_back(self):
        data_access, logger = build_data_access()

        with answering_with(graphql_partial_response):
            data = data_access.get_resource(graphql_query, {}, ["repository"])

        assert data["nameWithOwner"] == "chaoss/CollectOSS"
        assert data["forkCount"] == 18
        assert data["stargazers"] is None

    @pytest.mark.parametrize("graphql_response", graphql_responses_that_must_raise)
    def test_anything_but_a_readable_partial_still_raises(self, graphql_response):
        data_access, logger = build_data_access()

        with answering_with(graphql_response):
            with pytest.raises(Exception, match="Github Graphql Data Access Errors"):
                data_access.make_request(graphql_query, {})

        logger.warning.assert_not_called()

    def test_not_found_error_still_raises(self):
        data_access, logger = build_data_access()

        with answering_with(graphql_not_found_response):
            with pytest.raises(NotFoundException):
                data_access.make_request(graphql_query, {})

        logger.warning.assert_not_called()

    def test_null_data_section_still_raises(self):
        data_access, logger = build_data_access()

        with answering_with({"data": {"repository": None}}):
            with pytest.raises(Exception):
                data_access.get_resource(graphql_query, {}, ["repository"])

    def test_clean_response_is_returned_without_a_warning(self):
        data_access, logger = build_data_access()

        with answering_with(graphql_clean_response):
            response = data_access.make_request(graphql_query, {})

        assert response.json() == graphql_clean_response
        logger.warning.assert_not_called()

    def test_ignoring_not_found_errors_skips_the_check(self):
        data_access, logger = build_data_access(ingore_not_found_error=True)

        with answering_with(graphql_not_found_response):
            response = data_access.make_request(graphql_query, {})

        assert response.json() == graphql_not_found_response
        logger.warning.assert_not_called()
