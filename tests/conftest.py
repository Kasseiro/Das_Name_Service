import pytest


def pytest_addoption(parser):
    parser.addoption("--dns", default="127.0.0.1:5353", help="host:port of the server under test")
    parser.addoption("--admin", default="http://127.0.0.1:8080", help="admin API base URL")


@pytest.fixture(scope="session")
def dns_addr(request):
    host, port = request.config.getoption("--dns").rsplit(":", 1)
    return host, int(port)


@pytest.fixture(scope="session")
def admin_url(request):
    return request.config.getoption("--admin").rstrip("/")
