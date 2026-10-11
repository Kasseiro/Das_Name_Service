import dns.flags


def test_server_starts_with_documented_flags(server):
    """contract.md, Command line"""
    response = server.udp("ads.example.com.", "A")
    assert response.flags & dns.flags.QR
