"""Pytest configuration for shorter test output."""


def pytest_itemcollected(item):
    """Customize test node IDs for shorter output."""
    test_name = item.originalname or item.name
    test_name = test_name.removeprefix("test_")
    item._nodeid = test_name
